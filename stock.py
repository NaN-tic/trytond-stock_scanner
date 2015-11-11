# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from trytond.model import ModelView, fields
from trytond.pyson import Bool, Eval, If, And
from trytond.pool import Pool, PoolMeta
from trytond.modules.stock.move import STATES


__all__ = ['Configuration', 'Move', 'ShipmentIn',
    'ShipmentInReturn', 'ShipmentOut', 'ShipmentOutReturn']
__metaclass__ = PoolMeta

MIXIN_STATES = {
    'readonly': ~Eval('state').in_(['waiting', 'draft']),
    }


class Configuration:
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


class Move:
    __name__ = 'stock.move'
    scanned_quantity = fields.Float('Scanned Quantity',
        digits=(16, Eval('unit_digits', 2)), states=STATES,
        depends=['state', 'unit_digits'])
    pending_quantity = fields.Function(fields.Float('Pending Quantity',
            digits=(16, Eval('unit_digits', 2)), depends=['unit_digits'],
            help='Quantity pending to be scanned'),
        'get_pending_quantity')

    @staticmethod
    def default_scanned_quantity():
        return 0.

    @classmethod
    def get_pending_quantity(cls, moves, name):
        pool = Pool()
        Uom = pool.get('product.uom')
        quantity = {}
        for move in moves:
            quantity[move.id] = Uom.round(
                move.quantity - (move.scanned_quantity or 0.0),
                move.uom.rounding)
        return quantity


class StockScanMixin(object):
    scanner_enabled = fields.Function(fields.Boolean('Scanner Enabled'),
        'get_scanner_enabled')
    pending_moves = fields.Function(fields.One2Many('stock.move', None,
            'Pending Moves', states={
                'invisible': (~Eval('scanner_enabled', False)
                    | ~Eval('state', 'draft').in_(['waiting', 'draft'])),
                }, depends=['scanner_enabled', 'state'],
            help='List of pending products to be scan.'),
        'get_pending_moves')
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
        cls._error_messages.update({
                'product_not_pending': ('This product is not pending to be '
                    'scanned in this order.'),
                })
        cls._buttons.update({
                'scan': {
                    'invisible': ~And(
                            Eval('pending_moves', False),
                            Bool(Eval('scanned_product'))),
                    },
                'reset_scanned_quantities': {
                    'invisible': ~And(
                            Eval('pending_moves', False),
                            Eval('state').in_(['waiting', 'draft'])),
                    },
                'scan_all': {
                    'invisible': ~Eval('pending_moves', False),
                    },
                })

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
        return [l.id for l in self.get_pick_moves() if l.pending_quantity > 0]

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
            return {
                'scanned_uom': None,
                'scanned_quantity': None,
                }

        config = Config(1)

        scanned_moves = self.get_matching_moves()
        if scanned_moves:
            self.scanned_uom = scanned_moves[0].uom.id
            result = {}
            result['scanned_uom'] = scanned_moves[0].uom.id
            result['scanned_uom.rec_name'] = scanned_moves[0].uom.rec_name
            result['scanned_product_unit_digits'] = (
                self.on_change_with_scanned_product_unit_digits())
            if config.scanner_fill_quantity:
                result['scanned_quantity'] = scanned_moves[0].pending_quantity
            # elif not self.scanned_quantity or self.scanned_quantity == 0:
            #     result['scanned_quantity'] = 1
            return result
        # TODO: make configurable allow nont pending products?
        # self.raise_user_error('product_not_pending'
        return {
            'scanned_uom': self.scanned_product.default_uom.id,
            'scanned_uom.rec_name': self.scanned_product.default_uom.rec_name,
            'scanned_product_unit_digits': (
                self.scanned_product.default_uom.digits),
            }

    def get_matching_moves(self):
        """Get possible scanned move"""
        moves = []
        for move in self.pending_moves:
            if (move.product == self.scanned_product
                    and move.pending_quantity > 0):
                moves.append(move)
        return moves

    @staticmethod
    def default_scanned_product_unit_digits():
        return 2

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
            if not product or shipment.scanned_quantity <= 0:
                continue

            shipment.process_moves(shipment.get_matching_moves())
            shipment.clear_scan_values()
            shipment.save()  # TODO: move to save multiple shipments?

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
            return []

        if not moves:
            move = self.get_processed_move()
            move.save()
            moves = [move]

        for move in moves:
            # find move with the same quantity
            scanned_qty_move_uom = Uom.compute_qty(self.scanned_uom,
                self.scanned_quantity, move.uom, round=False)
            if (abs(move.pending_quantity - scanned_qty_move_uom)
                    < move.uom.rounding):
                move.scanned_quantity = move.quantity
                move.save()
                return [move]

        # Find move with the nearest pending quantity
        moves.sort(key=lambda m: m.internal_quantity)
        found_move = None
        for move in moves:
            scanned_qty_move_uom = Uom.compute_qty(self.scanned_uom,
                self.scanned_quantity, move.uom, round=False)
            found_move = move
            if move.quantity > scanned_qty_move_uom:
                break
        found_move.scanned_quantity = scanned_qty_move_uom
        found_move.save()
        return [found_move]

    def clear_scan_values(self):
        self.scanned_product = None
        self.scanned_quantity = None

    @classmethod
    @ModelView.button
    def reset_scanned_quantities(cls, shipments):
        Move = Pool().get('stock.move')
        all_pending_moves = []
        for shipment in shipments:
            all_pending_moves.extend(shipment.pending_moves)
        if all_pending_moves:
            Move.write(all_pending_moves, {
                    'scanned_quantity': 0.,
                    })

    @classmethod
    @ModelView.button
    def scan_all(cls, shipments):
        for shipment in shipments:
            for move in shipment.pending_moves:
                move.scanned_quantity = move.quantity
                move.save()

    @classmethod
    def set_scanned_quantity_as_quantity(cls, shipments, moves_field_name):
        pool = Pool()
        Config = pool.get('stock.configuration')
        if Config.scanner_on_shipment_type(cls.__name__):
            for shipment in shipments:
                for move in getattr(shipment, moves_field_name, []):
                    move.quantity = move.scanned_quantity
                    move.save()


class ShipmentIn(StockScanMixin):
    __metaclass__ = PoolMeta
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


class ShipmentInReturn(ShipmentIn):
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.in.return'

    def get_processed_move(self):
        move = super(ShipmentIn, self).get_processed_move()
        move.from_location = self.from_location
        move.to_location = self.to_location
        # TODO: add to scanner or improve it
        move.unit_price = move.product.cost_price
        return move

    @classmethod
    def wait(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'outgoing_moves')
        super(ShipmentInReturn, cls).wait(shipments)


class ShipmentOut(StockScanMixin):
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.out'

    def get_pick_moves(self):
        return self.inventory_moves

    def get_processed_move(self):
        move = super(ShipmentIn, self).get_processed_move()
        move.from_location = self.warehouse_storage
        move.to_location = self.warehouse_output
        # TODO: add to scanner or improve it
        move.unit_price = move.product.list_price
        return move

    @classmethod
    def assign_try(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'inventory_moves')
        return super(ShipmentOut, cls).assign_try(shipments)


class ShipmentOutReturn(ShipmentOut):
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.out.return'

    def get_pick_moves(self):
        return self.incoming_moves

    def get_processed_move(self):
        move = super(ShipmentIn, self).get_processed_move()
        move.from_location = self.customer_location
        move.to_location = self.warehouse_input
        # TODO: add to scanner or improve it
        move.unit_price = move.product.list_price
        return move

    @classmethod
    def receive(cls, shipments):
        cls.set_scanned_quantity_as_quantity(shipments, 'incoming_moves')
        super(ShipmentOutReturn, cls).receive(shipments)
