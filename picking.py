# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.pool import Pool
from trytond.transaction import Transaction


class StockPickingShipmentOutAsk(ModelView):
    'Stock Picking Shipment Out Ask'
    __name__ = 'stock.picking.shipment.out.ask'
    shipment = fields.Char('Shipment')
    to_pick = fields.Selection('get_to_pick', 'To Pick', sort=True)

    @classmethod
    def get_to_pick(cls):
        pool = Pool()
        Shipment = pool.get('stock.shipment.out')
        return [(s.id, s.rec_name) for s in Shipment.search([
            ('state', '=', 'assigned'),
            ])]


class StockPickingShipmentOutScan(ModelView):
    'Stock Picking Shipment Out Scan'
    __name__ = 'stock.picking.shipment.out.scan'
    shipment = fields.Many2One('stock.shipment.out', 'Shipment', readonly=True)
    product = fields.Many2One('product.product', 'Product', readonly=True)
    to_pick = fields.Char('To pick')
    pending_moves = fields.Text('APP Pending Moves', readonly=True)


class StockPickingShipmentOutResult(ModelView):
    "Stock Picking Shipment Out Result"
    __name__ = 'stock.picking.shipment.out.result'
    shipment = fields.Many2One('stock.shipment.out', 'Shipment', readonly=True)
    note = fields.Text('Note', readonly=True)


class StockPickingShipmentOut(Wizard):
    "Stock Picking Shipment Out Ask"
    __name__ = 'stock.picking.shipment.out'
    start_state = 'ask'
    ask = StateView('stock.picking.shipment.out.ask',
        'stock_scanner.stock_picking_shipment_out_start', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Scan', 'scan', 'tryton-ok', True),
            ])
    scan = StateView('stock.picking.shipment.out.scan',
        'stock_scanner.stock_picking_shipment_out_scan', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Back', 'ask', 'tryton-back'),
            Button('Pick', 'pick', 'tryton-launch', True),
            Button('Packed', 'packed', 'tryton-ok'),
            ])
    pick = StateTransition()
    packed = StateTransition()
    result = StateView('stock.picking.shipment.out.result',
        'stock_scanner.stock_picking_shipment_out_result', [
            Button('Start', 'ask', 'tryton-back', True),
            Button('Done', 'end', 'tryton-ok'),
            ])

    def transition_pick(self):
        pool = Pool()
        Shipment = pool.get('stock.shipment.out')
        Move = pool.get('stock.move')

        shipment = Shipment(self.scan.shipment)

        def qty(value):
            try:
                return float(value)
            except ValueError:
                return False

        shipment = Shipment(self.scan.shipment)
        to_pick = self.scan.to_pick
        quantity = qty(to_pick)

        if (shipment.scanned_product and (quantity or quantity == 0.0)
                and len(str(int(quantity))) < 5):
            # picking is 0 means set scanned_quantity and quantity are 0
            if quantity == 0.0:
                moves = shipment.get_matching_moves()
                Move.write(moves, {'scanned_quantity': 0.0, 'quantity': 0.0})
                shipment.clear_scan_values()
                shipment.save()
            else:
                shipment.scanned_quantity = shipment.scanned_uom.round(quantity)
                shipment.save()
                Shipment.scan([shipment])
                shipment = Shipment(shipment.id)
        else:
            for move in shipment.pending_moves:
                if move.matches_scan(to_pick):
                    self.scan.product = move.product
                    shipment.scanned_product = move.product
                    shipment.scanned_quantity = 1
                    shipment.on_change_scanned_product()
                    shipment.save()
                    Shipment.scan([shipment])
                    shipment.scanned_product = move.product
                    shipment.save()
                    break
            else:
                self.scan.product = None
        return 'scan'

    def transition_packed(self):
        pool = Pool()
        Shipment = pool.get('stock.shipment.out')

        with Transaction().set_context(_skip_warnings=True):
            shipment = Shipment(self.scan.shipment)
            Shipment.assign([shipment])
            Shipment.pick([shipment])
            Shipment.pack([shipment])

        return 'result'

    def default_ask(self, fields):
        # reset values in case start first step (select a shipment)
        self.scan.shipment = None
        self.scan.product = None
        self.scan.to_pick = None
        self.scan.pending_moves = None
        return {}

    def default_scan(self, fields):
        pool = Pool()
        Shipment = pool.get('stock.shipment.out')
        Location = pool.get('stock.location')

        # Get storage_location locations
        storages = Location.search([('type', '=', 'warehouse')])
        storage_locations = []
        for storage in storages:
            storage_locations.append(storage.storage_location)

        if self.ask.to_pick is not None:
            shipment = Shipment(self.ask.to_pick)
        else:
            shipments = Shipment.search([
                ('state', '=', 'assigned'),
                ('number', '=', self.ask.shipment),
                ], limit=1)
            if not shipments:
                return {}
            shipment, = shipments

        defaults = {}
        defaults['shipment'] = shipment.id
        if hasattr(self.scan, 'product'):
            defaults['product'] = self.scan.product and self.scan.product.id

        pending_moves = []
        locations_move = {}
        for move in shipment.pending_moves:
            locations_move.setdefault(move.from_location, [])
            locations_move[move.from_location].append(move)

        for location in sorted(locations_move, key=lambda x: x.name):
            if location not in storage_locations:
                pending_moves.append(
                    u'<div align="left">'
                    '<font size="4"><u><b>{}</b></u></font>'
                    '</div>'.format(location.name))
            for move in locations_move[location]:
                pending_moves.append(
                    u'<div align="left">'
                    '<font size="4">{} <b>{}</b></font>'
                    '</div>'.format(move.pending_quantity,
                        move.product.rec_name))
        defaults['pending_moves'] = '\n'.join(pending_moves)
        return defaults

    def default_result(self, fields):
        defaults = {}
        defaults['shipment'] = self.scan.shipment and self.scan.shipment.id
        return defaults
