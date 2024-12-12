# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import Workflow, ModelView, fields, dualmethod
from trytond.pyson import Bool, Eval, If, And
from trytond.pool import Pool, PoolMeta
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from operator import itemgetter
import datetime


__all__ = ['Configuration', 'Move', 'ShipmentIn',
    'ShipmentOut', 'ShipmentOutReturn']


MIXIN_STATES = {
    'readonly': ~Eval('state').in_(['waiting', 'draft', 'assigned']),
    }


class Configuration(metaclass=PoolMeta):
    __name__ = 'stock.configuration'

    scanner_on_shipment_internal = fields.Boolean('Scanner on InternalShipments?')
    scanner_on_shipment_in = fields.Boolean('Scanner on Supplier Shipments?')
    scanner_on_shipment_in_return = fields.Boolean(
        'Scanner on Supplier Return Shipments?')
    scanner_on_shipment_out = fields.Boolean('Scanner on Customer Shipments?')
    scanner_on_shipment_out_return = fields.Boolean(
        'Scanner on Customer Return Shipments?')
    scanner_fill_quantity = fields.Boolean('Fill Quantity',
        help='If marked pending quantity is loaded when product is scanned')
    scanner_pending_quantity = fields.Boolean("Scanner Pending Quantity",
        states={
            'invisible': ~Eval('scanner_fill_quantity'),
        }, depends=['scanner_fill_quantity'],
        help="Quantity scanned are pending quantities")

    @classmethod
    def scanner_on_shipment_type(cls, shipment_type):
        config = cls(1)
        if shipment_type == 'stock.shipment.internal':
            return config.scanner_on_shipment_internal
        if shipment_type == 'stock.shipment.in':
            return config.scanner_on_shipment_in
        if shipment_type == 'stock.shipment.in.return':
            return config.scanner_on_shipment_in_return
        if shipment_type == 'stock.shipment.out':
            return config.scanner_on_shipment_out
        if shipment_type == 'stock.shipment.out.return':
            return config.scanner_on_shipment_out_return


class Move(metaclass=PoolMeta):
    __name__ = 'stock.move'
    scanned_quantity = fields.Float('Scanned Quantity',
        digits='uom', states={
            'readonly': Eval('state').in_(['cancelled', 'done']),
        }, depends=['state'])
    pending_quantity = fields.Function(fields.Float('Pending Quantity',
        digits='uom', help='Quantity pending to be scanned'),
        'get_pending_quantity', searcher='search_pending_quantity')

    @classmethod
    def __setup__(cls):
        super(Move, cls).__setup__()
        # We need to delete 'quantity' from _deny_modify_assigned to be able to
        # use set_scanned_quantity_as_quantity function in pack function.
        if 'quantity' in cls._deny_modify_assigned:
            cls._deny_modify_assigned.remove('quantity')

    @staticmethod
    def default_scanned_quantity():
        return 0.

    def get_quantity_for_value(self):
        ShipmentIn = Pool().get('stock.shipment.in')
        if isinstance(self.shipment, ShipmentIn):
            return self.scanned_quantity
        return self.quantity

    @classmethod
    def get_pending_quantity(cls, moves, name):
        quantities = dict((x.id, 0.0) for x in moves)
        for move in moves:
            quantity = move.quantity
            scanned_quantity = move.scanned_quantity or 0.0
            if (quantity >= scanned_quantity):
                quantities[move.id] = move.uom.round(quantity - scanned_quantity)
        return quantities

    @classmethod
    def search_pending_quantity(cls, name, domain):
        table = cls.__table__()
        _, operator, _ = domain
        if operator == '<':
            sql_where = (table.quantity < table.scanned_quantity)
        elif operator == '=':
            sql_where = (table.quantity == table.scanned_quantity)
        else:
            sql_where = (table.quantity > table.scanned_quantity)
        query = table.select(table.id, where=sql_where)
        return [('id', 'in', query)]

    @classmethod
    def copy(cls, moves, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default['scanned_quantity'] = cls.default_scanned_quantity()
        return super(Move, cls).copy(moves, default=default)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, moves):
        super(Move, cls).draft(moves)
        cls.write(moves, {
                'scanned_quantity': cls.default_scanned_quantity(),
                })

    def matches_scan(self, input_):
        if self.product.code == input_:
            return True
        for identifier in self.product.identifiers:
            if identifier.code == input_:
                return True
        return False


class StockScanMixin(object):
    __slots__ = ()
    scanner_enabled = fields.Function(fields.Boolean('Scanner Enabled'),
        'get_scanner_enabled')
    pending_moves = fields.Function(fields.One2Many('stock.move', None,
            'Pending Moves', states={
                'invisible': (~Eval('scanner_enabled', False)
                    | ~Eval('state', 'draft').in_(['waiting', 'draft',
                            'assigned'])),
                }, depends=['scanner_enabled', 'state'],
            help='List of pending products to be scan.'),
        'get_pending_moves', setter='set_pending_moves')
    scannable_products = fields.Function(fields.Many2Many('product.product',
            None, None, 'Scannable Products',
            context={
                'company': Eval('company', -1),
                },
            depends=['company']),
        'get_scannable_products')
    scanned_product = fields.Many2One('product.product', 'Scanned product',
        domain=[
            ('type', '!=', 'service'),
            If(Bool(Eval('scannable_products')),
                ('id', 'in', Eval('scannable_products')),
                ()),
            ],
        context={
            'company': Eval('company', -1),
            },
        states=MIXIN_STATES, depends=['scannable_products', 'state', 'company'],
        help='Scan the code of the next product.')
    scanned_uom = fields.Many2One('product.uom', 'Scanned UoM', states={
            'readonly': True,
        })
    scanned_quantity = fields.Float('Quantity', 'scanned_uom',
        states=MIXIN_STATES, depends=['state'],
        help='Quantity of the scanned product.')

    @classmethod
    def __setup__(cls):
        super(StockScanMixin, cls).__setup__()
        cls._buttons.update({
                'scan': {
                    'invisible': ~And(
                            Eval('pending_moves', False),
                            Bool(Eval('scanned_product'))),
                    'depends': ['pending_moves', 'scanned_product'],
                },
                'reset_scanned_quantities': {
                    'icon': 'tryton-refresh',
                    'invisible': ~Eval('state').in_(['waiting', 'draft',
                            'assigned']),
                    'depends': ['state'],
                },
                'scan_all': {
                    'icon': 'tryton-warning',
                    'invisible': ~Eval('state').in_(['waiting', 'draft',
                            'assigned']),
                    'depends': ['state'],
                },
                })
        cls._scanner_allow_delete = ['stock.shipment.in']

    @classmethod
    def default_scanner_enabled(cls):
        pool = Pool()
        Config = pool.get('stock.configuration')
        return Config.scanner_on_shipment_type(cls.__name__)

    @classmethod
    def get_scanner_enabled(cls, shipments, name):
        scanner_enabled = cls.default_scanner_enabled()
        return {}.fromkeys([s.id for s in shipments], scanner_enabled)

    def get_pending_moves(self, name):
        return [x.id for x in self.get_pick_moves()
            if (x.pending_quantity > 0 and x.state not in ('cancelled', 'done'))]

    @classmethod
    def set_pending_moves(cls, shipments, name, value):
        Move = Pool().get('stock.move')

        to_write = []
        for v in value:
            action = v[0]
            # omit "add" action
            if action == 'write':
                actions = iter(v[1:])
                for move_ids, values in zip(actions, actions):
                    to_write.extend((Move.browse(move_ids), values))
            elif action == 'delete':
                if all([shipment for shipment in shipments
                        if shipment.__name__ in cls._scanner_allow_delete]):
                    move_ids = v[1]
                    if move_ids:
                        # not delete. Set shipment to none to allow pick in
                        # other shipment
                        to_write.extend((Move.browse(move_ids),
                                {'shipment': None}))

        if to_write:
            Move.write(*to_write)

    def get_pick_moves(self):
        return self.moves

    def get_scannable_products(self, name):
        moves = self.get_pick_moves()
        product_ids = set([m.product.id for m in moves])
        return list(product_ids)

    @fields.depends('scanned_product', 'pending_moves', 'scanned_quantity')
    def on_change_scanned_product(self):
        pool = Pool()
        Config = pool.get('stock.configuration')
        if not self.scanned_product:
            self.scanned_uom = None
            self.scanned_quantity = None
            return

        config = Config(1)
        scanned_moves = self.get_matching_moves()
        if scanned_moves:
            scanned_move = scanned_moves[0]
            self.scanned_uom = scanned_move.uom

            if config.scanner_fill_quantity:
                self.scanned_quantity = (scanned_move.pending_quantity
                    if config.scanner_pending_quantity else 1)
            return
        self.scanned_uom = self.scanned_product.default_uom

    def get_matching_moves(self):
        """Get possible scanned move"""
        moves = []
        for move in self.pending_moves:
            if (move.product == self.scanned_product
                    and move.pending_quantity > 0):
                moves.append(move)
        return moves

    @classmethod
    @ModelView.button
    def scan(cls, shipments):
        for shipment in shipments:
            product = shipment.scanned_product
            scanned_quantity = shipment.scanned_quantity
            if (not product or not scanned_quantity
                    or shipment.scanned_quantity <= 0):
                continue

            shipment.process_moves(shipment.get_matching_moves())
            shipment.clear_scan_values()
            shipment.save()  # TODO: move to save multiple shipments?

    @classmethod
    @ModelView.button
    def scan_all(cls, shipments):
        Warning = Pool().get('res.user.warning')

        to_save = []
        for shipment in shipments:
            warning_name = 'scan_all,%s' % shipment
            if Warning.check(warning_name):
                raise UserWarning(warning_name,
                    gettext('stock_scanner.msg_scan_all'))
            pending_moves = shipment.pending_moves[:]
            for move in pending_moves:
                shipment.scanned_product = move.product
                shipment.scanned_quantity = move.quantity
                shipment.scanned_uom = move.uom
                shipment.process_moves([move])
                shipment.clear_scan_values()
                to_save.append(shipment)
        cls.save(to_save)

    def get_processed_move(self):
        pool = Pool()
        Move = pool.get('stock.move')

        move = Move()
        move.company = self.company
        move.product = self.scanned_product
        move.uom = self.scanned_uom
        move.quantity = self.scanned_quantity
        move.shipment = str(self)
        move.planned_date = self.planned_date
        move.currency = self.company.currency
        return move

    def process_moves(self, moves):
        pool = Pool()
        Uom = pool.get('product.uom')

        if (not self.scanned_quantity or not self.scanned_uom
                or self.scanned_quantity < self.scanned_uom.rounding):
            return

        if not moves:
            move = self.get_processed_move()
            move.save()
            moves = [move]

        for move in moves:
            # find move with the same quantity
            scanned_qty_in_move_uom = Uom.compute_qty(self.scanned_uom,
                self.scanned_quantity, move.uom, round=False)
            if (abs(move.pending_quantity - scanned_qty_in_move_uom)
                    < move.uom.rounding):
                move.scanned_quantity = move.quantity
                move.save()
                return move

        # Find move with the nearest pending quantity
        moves.sort(key=lambda m: m.internal_quantity)
        found_move = None
        for move in moves:
            scanned_qty_move_uom = Uom.compute_qty(self.scanned_uom,
                self.scanned_quantity, move.uom, round=False)
            found_move = move
            if move.quantity > scanned_qty_move_uom:
                break

        if found_move:
            if found_move.scanned_quantity:
                found_move.scanned_quantity += scanned_qty_move_uom
            else:
                found_move.scanned_quantity = scanned_qty_move_uom
            found_move.save()
            return found_move

    def clear_scan_values(self):
        self.scanned_product = None
        self.scanned_quantity = None
        self.scanned_uom = None

    @classmethod
    @ModelView.button
    def reset_scanned_quantities(cls, shipments):
        Move = Pool().get('stock.move')
        all_pending_moves = []
        for shipment in shipments:
            all_pending_moves.extend(shipment.get_pick_moves())
        if all_pending_moves:
            Move.write(all_pending_moves, {
                    'scanned_quantity': 0.,
                    })

    @classmethod
    def set_scanned_quantity_as_quantity(cls, shipments, moves_field_name):
        pool = Pool()
        Config = pool.get('stock.configuration')
        if Config.scanner_on_shipment_type(cls.__name__):
            for shipment in shipments:
                for move in getattr(shipment, moves_field_name, []):
                    move.quantity = move.scanned_quantity
                    move.save()


class ShipmentIn(StockScanMixin, metaclass=PoolMeta):
    __name__ = 'stock.shipment.in'

    def get_pick_moves(self):
        return self.incoming_moves

    def get_processed_move(self):
        move = super(ShipmentIn, self).get_processed_move()
        move.from_location = self.supplier_location
        move.to_location = self.warehouse_input
        # TODO: add to scanner or improve it
        move.unit_price = move.product.cost_price
        return move

    @classmethod
    def receive(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'incoming_moves')
        super(ShipmentIn, cls).receive(shipments)

    def get_pending_moves(self, name):
        moves = [move for move in self.get_pick_moves() if
            move.pending_quantity > 0]
        tuples = []
        for move in moves:
            if move.origin and hasattr(move.origin, 'purchase'):
                tuples.append((move, move.origin.purchase.purchase_date))
            else:
                tuples.append((move, datetime.date.today()))
        tuples = sorted(tuples, key=itemgetter(1))
        moves = [x[0].id for x in tuples]
        return moves


class ShipmentOut(StockScanMixin, metaclass=PoolMeta):
    __name__ = 'stock.shipment.out'

    def get_pick_moves(self):
        return self.inventory_moves

    def get_processed_move(self):
        move = super(ShipmentOut, self).get_processed_move()
        move.from_location = self.warehouse_storage
        move.to_location = self.warehouse_output
        # TODO: add to scanner or improve it
        move.unit_price = move.product.list_price
        return move

    @classmethod
    def pick(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'inventory_moves')
        super(ShipmentOut, cls).pick(shipments)


class ShipmentOutReturn(ShipmentOut, metaclass=PoolMeta):
    __name__ = 'stock.shipment.out.return'

    def get_pick_moves(self):
        return self.incoming_moves

    def get_processed_move(self):
        move = super(ShipmentOutReturn, self).get_processed_move()
        move.from_location = self.customer_location
        move.to_location = self.warehouse_input
        # TODO: add to scanner or improve it
        move.unit_price = move.product.list_price
        return move

    @classmethod
    def receive(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'incoming_moves')
        super(ShipmentOutReturn, cls).receive(shipments)


class ShipmentInternal(StockScanMixin, metaclass=PoolMeta):
    __name__ = 'stock.shipment.internal'

    def get_pick_moves(self):
        if self.transit_location:
            return self.incoming_moves
        else:
            return self.moves

    @classmethod
    def receive(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'incoming_moves')
        super().receive(shipments)

    def get_pending_moves(self, name):
        moves = [move for move in self.get_pick_moves() if
            move.pending_quantity > 0]
        tuples = []
        for move in moves:
            if (move.origin and hasattr(move.origin, 'purchase') and
                    move.origin.purchase):
                tuples.append((move, move.origin.purchase.purchase_date))
            else:
                tuples.append((move, datetime.date.today()))
        tuples = sorted(tuples, key=itemgetter(1))
        moves = [x[0].id for x in tuples]
        return moves

    @dualmethod
    def assign_try(cls, shipments):
        for shipment in shipments:
            field_name = 'moves'
            if shipment.transit_location:
                field_name = 'outgoing_moves'
            print("field_name:", field_name)
            print("shipment:", shipment.moves)
            cls.set_scanned_quantity_as_quantity([shipment], field_name)
        super().assign(shipments)



    @classmethod
    def assign(cls, shipments):
        for shipment in shipments:
            field_name = 'moves'
            if shipment.transit_location:
                field_name = 'outgoing_moves'
            cls.set_scanned_quantity_as_quantity([shipment], field_name)
        super().assign(shipments)












