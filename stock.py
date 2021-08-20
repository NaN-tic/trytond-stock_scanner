# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import Workflow, ModelView, fields
from trytond.pyson import Bool, Eval, If, And
from trytond.pool import Pool, PoolMeta
from trytond.model.exceptions import AccessError
from trytond.modules.stock.move import STATES
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

    scanner_on_shipment_in = fields.Boolean('Scanner on Supplier Shipments?')
    scanner_on_shipment_in_return = fields.Boolean(
        'Scanner on Supplier Return Shipments?')
    scanner_on_shipment_out = fields.Boolean('Scanner on Customer Shipments?')
    scanner_on_shipment_out_return = fields.Boolean(
        'Scanner on Customer Return Shipments?')
    scanner_fill_quantity = fields.Boolean('Fill Quantity',
        help='If marked pending quantity is loaded when product is scanned')

    @classmethod
    def scanner_on_shipment_type(cls, shipment_type):
        config = cls(1)
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
        digits=(16, Eval('unit_digits', 2)), states=STATES,
        depends=['state', 'unit_digits'])
    pending_quantity = fields.Function(fields.Float('Pending Quantity',
            digits=(16, Eval('unit_digits', 2)), depends=['unit_digits'],
            help='Quantity pending to be scanned'),
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
        quantity = {}
        for move in moves:
            quantity[move.id] = move.uom.round(
                move.quantity - (move.scanned_quantity or 0.0))
        return quantity

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
    def write(cls, *args):
        actions = iter(args)
        for moves, values in zip(actions, actions):
            # Ensure quantity is not set to a value greater than the one
            # assigned, given that we remove 'quantity' from
            # cls._deny_modify_assigned in __setup__
            if 'quantity' in values:
                for move in moves:
                    if (move.state == 'assigned'
                            and values['quantity'] > move.quantity):
                        raise AccessError(
                            gettext('stock.msg_move_modify_assigned',
                                move=move.rec_name))
        super(Move, cls).write(*args)

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
            None, None, 'Scannable Products'),
        'get_scannable_products')
    scanned_product = fields.Many2One('product.product', 'Scanned product',
        domain=[
            ('type', '!=', 'service'),
            If(Bool(Eval('scannable_products')),
                ('id', 'in', Eval('scannable_products')),
                ()),
            ],
        states=MIXIN_STATES, depends=['scannable_products', 'state'],
        help='Scan the code of the next product.')
    scanned_uom = fields.Many2One('product.uom', 'Scanned UoM', states={
            'readonly': True,
            })
    scanned_product_unit_digits = fields.Function(
        fields.Integer('Scanned Product Unit Digits'),
        'on_change_with_scanned_product_unit_digits')
    scanned_quantity = fields.Float('Quantity',
        digits=(16, Eval('scanned_product_unit_digits', 2)),
        states=MIXIN_STATES, depends=['scanned_product_unit_digits', 'state'],
        help='Quantity of the scanned product.')

    @classmethod
    def __setup__(cls):
        super(StockScanMixin, cls).__setup__()
        cls._buttons.update({
                'scan': {
                    'invisible': ~And(
                            Eval('pending_moves', False),
                            Bool(Eval('scanned_product'))),
                },
                'reset_scanned_quantities': {
                    'icon': 'tryton-refresh',
                    'invisible': ~Eval('state').in_(['waiting', 'draft',
                            'assigned'])
                },
                'scan_all': {
                    'icon': 'tryton-warning',
                    'invisible': ~Eval('state').in_(['waiting', 'draft',
                            'assigned'])
                },
                })
        cls._scanner_allow_delete = ['stock.shipment.in']

    @classmethod
    def default_scanner_enabled(cls):
        pool = Pool()
        Config = pool.get('stock.configuration')
        return Config.scanner_on_shipment_type(cls.__name__)

    @staticmethod
    def default_scanned_product_unit_digits():
        return 2

    @classmethod
    def get_scanner_enabled(cls, shipments, name):
        scanner_enabled = cls.default_scanner_enabled()
        return {}.fromkeys([s.id for s in shipments], scanner_enabled)

    def get_pending_moves(self, name):
        return [l.id for l in self.get_pick_moves() if l.pending_quantity > 0]

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
                        # not delete. Set shipment to none to allow pick in other shipment
                        to_write.extend((Move.browse(move_ids), {'shipment': None}))

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
            self.scanned_uom = scanned_moves[0].uom

            self.scanned_product_unit_digits = (
                self.on_change_with_scanned_product_unit_digits())
            if config.scanner_fill_quantity:
                self.scanned_quantity = scanned_moves[0].pending_quantity
            return


        self.scanned_uom = self.scanned_product.default_uom
        self.scanned_product_unit_digits = (
            self.scanned_product.default_uom.digits)

    def get_matching_moves(self):
        """Get possible scanned move"""
        moves = []
        for move in self.pending_moves:
            if (move.product == self.scanned_product
                    and move.pending_quantity > 0):
                moves.append(move)
        return moves

    @fields.depends('scanned_uom', 'scanned_product')
    def on_change_with_scanned_product_unit_digits(self, name=None):
        if self.scanned_uom:
            return self.scanned_uom.digits
        elif self.scanned_product:
            return self.scanned_product.default_uom.digits
        return self.default_scanned_product_unit_digits()

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
        pool = Pool()
        Warning = pool.get('res.user.warning')
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
        cls.save(shipments)

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

    @classmethod
    @ModelView.button
    def reset_scanned_quantities(cls, shipments):
        Move = Pool().get('stock.move')
        all_pending_moves = []
        for shipment in shipments:
            all_pending_moves.extend(shipment.incoming_moves)
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
    def pack(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'inventory_moves')
        return super(ShipmentOut, cls).pack(shipments)


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
