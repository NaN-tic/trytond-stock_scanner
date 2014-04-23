# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.pyson import Eval, Not, And, Bool
from trytond.pool import Pool, PoolMeta
from trytond.modules.stock.move import STATES


__all__ = ['Configuration', 'Move', 'Product', 'ProductSupplier', 'ShipmentIn',
    'ShipmentInReturn', 'ShipmentOut', 'ShipmentOutReturn']

__metaclass__ = PoolMeta


class Configuration:
    __name__ = 'stock.configuration'

    scanner_fill_quantity = fields.Function(fields.Boolean('Fill Quantity',
            help='If marked pending quantity is loaded when product is'
            ' scanned'), 'get_fill_quantity', setter='set_fill_quantity')
    scanner_fill_property = fields.Property(fields.Numeric('Fill quantity'))

    def get_fill_quantity(self, name):
        return self.scanner_fill_property == 1

    @classmethod
    def set_fill_quantity(cls, ids, name, value):
        val = 1 if value else 0
        cls.write([ids], {
                'scanner_fill_property': val,
            })

MIXIN_STATES = {
    'readonly': ~Eval('state').in_(['waiting', 'draft']),
}


class StockScanMixin(object):

    pending_moves = fields.Function(fields.One2Many('stock.move', None,
        'Pending Moves', help='List of pending products to be received.'),
        'get_pending_moves')
    scanned_product = fields.Many2One('product.product', 'Scanned product',
        domain=[('type', '!=', 'service')], depends=['state'],
        on_change=['scanned_product', 'pending_moves', 'scanned_quantity'],
        states=MIXIN_STATES, help='Scan the code of the next product.')
    scanned_quantity = fields.Float('Quantity',
        digits=(16, 4), depends=['state'],
        states=MIXIN_STATES, help='Quantity of the scanned product.')

    @classmethod
    def __setup__(cls):
        super(StockScanMixin, cls).__setup__()
        cls._error_messages.update({
                'product_not_pending': ('This product is not pending to be '
                    'scanned in this order.'),
                })
        cls._buttons.update({
                'scan': {
                        'invisible': Not(And(
                                        Eval('pending_moves', False),
                                        Bool(Eval('scanned_product', {})),
                                      )),
                    },
                'init_quantities': {
                        'invisible': Not(And(
                                Eval('pending_moves', False),
                                Eval('state').in_(['waiting', 'draft']),
                            ))
                    },
                })

    def on_change_scanned_product(self):
        pool = Pool()
        Config = pool.get('stock.configuration')
        if not self.scanned_product:
            return {}

        config = Config(1)

        result = {}
        for move in self.pending_moves:
            if move.product == self.scanned_product:
                if config.scanner_fill_quantity:
                    result['scanned_quantity'] = move.pending_quantity
                elif not self.scanned_quantity or self.scanned_quantity == 0:
                    result['scanned_quantity'] = 1
                return result

        self.raise_user_error('product_not_pending')

    def get_pick_moves(self):
        return self.moves

    def get_pending_moves(self, name):
        return [l.id for l in self.get_pick_moves() if l.pending_quantity > 0]

    def get_matching_moves(self):
        """Get possible scanned move"""
        moves = []
        for move in self.pending_moves:
            if move.product == self.scanned_product and \
                    move.pending_quantity > 0:
                moves.append(move)
        return moves

    @classmethod
    def process_moves(cls, moves):
        for move in moves:
            qty = min(move.shipment.scanned_quantity, move.pending_quantity)
            if qty == 0:
                continue

            move.received_quantity = (move.received_quantity or 0.0) + qty
            move.save()

    @classmethod
    @ModelView.button
    def scan(cls, shipments):
        moves_to_process = []
        for shipment in shipments:
            product = shipment.scanned_product
            if not product or not shipment.scanned_quantity > 0:
                continue

            moves_to_process.extend(shipment.get_matching_moves())
        cls.process_moves(moves_to_process)

        cls.clear_scan_values(shipments)

    @classmethod
    def clear_scan_values(cls, shipments):
        cls.write(shipments, {
            'scanned_product': None,
            'scanned_quantity': 0,
        })

    @classmethod
    @ModelView.button
    def init_quantities(cls, shipments):
        for shipment in shipments:
            for move in shipment.pending_moves:
                move.received_quantity = move.quantity
                move.save()

    @classmethod
    def force_split(cls, shipments):
        for shipment in shipments:
            for move in shipment.pending_moves:
                if move.received_quantity and \
                        move.received_quantity < move.quantity:
                    move.quantity = move.received_quantity
                    move.save()


class ShipmentIn(StockScanMixin):
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.in'

    def get_pick_moves(self):
        return self.incoming_moves

    @classmethod
    def receive(cls, shipments):
        cls.force_split(shipments)
        super(ShipmentIn, cls).receive(shipments)


class ShipmentInReturn(ShipmentIn):
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.in.return'

    def get_pick_moves(self):
        return self.outgoing_moves

    @classmethod
    def wait(cls, shipments):
        cls.force_split(shipments)
        super(ShipmentInReturn, cls).wait(shipments)


class ShipmentOut(StockScanMixin):
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.out'

    def get_pick_moves(self):
        return self.inventory_moves

    @classmethod
    def assign_try(cls, shipments):
        cls.force_split(shipments)
        return super(ShipmentOut, cls).assign_try(shipments)


class ShipmentOutReturn(ShipmentOut):
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.out.return'

    def get_pick_moves(self):
        return self.incoming_moves

    @classmethod
    def receive(cls, shipments):
        cls.force_split(shipments)
        super(ShipmentOut, cls).receive(shipments)


class Move:
    __name__ = 'stock.move'

    received_quantity = fields.Float('Received Quantity',
        digits=(16, Eval('unit_digits', 2)), states=STATES,
        depends=['state', 'unit_digits'], help='Quantity of product received')
    pending_quantity = fields.Function(fields.Float('Pending Quantity',
        digits=(16, Eval('unit_digits', 2)), depends=['unit_digits'],
        help='Quantity pending to be received'), 'get_pending_quantity')

    @classmethod
    def get_pending_quantity(cls, moves, names):
        quantity = {}
        for move in moves:
            quantity[move.id] = move.quantity - (move.received_quantity or 0.0)
        return {'pending_quantity': quantity}


class Product:
    __name__ = 'product.product'

    @classmethod
    def search_rec_name(cls, name, clause):
        pool = Pool()
        ProductSupplier = pool.get('purchase.product_supplier')

        ids = [p.product.id for p in ProductSupplier.search([
                    ('barcode',) + tuple(clause[1:])], order=[])]
        if ids:
            ids = map(int, cls.search([('template', 'in', ids)]))
            ids += map(int,
                cls.search([('template.name',) + tuple(clause[1:])], order=[]))
            return [('id', 'in', ids)]
        return super(Product, cls).search_rec_name(name, clause)


class ProductSupplier:
    'Product Supplier'
    __name__ = 'purchase.product_supplier'

    barcode = fields.Char('Barcode', help='The barcode for this product of '
        'this supplier.')
