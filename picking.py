# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.pool import Pool
from trytond.i18n import gettext
from trytond.exceptions import UserError, UserWarning


class StockPickingShipmentInAsk(ModelView):
    'Stock Picking Shipment In Ask'
    __name__ = 'stock.picking.shipment.in.ask'
    shipment = fields.Char('Shipment')
    to_pick = fields.Selection('get_to_pick', 'To Pick', sort=True)

    @classmethod
    def get_to_pick(cls):
        pool = Pool()
        Shipment = pool.get('stock.shipment.in')
        return [(s.id, s.rec_name) for s in Shipment.search([
            ('state', '=', 'received'),
            ])]


class StockPickingShipmentInScan(ModelView):
    'Stock Picking Shipment In Scan'
    __name__ = 'stock.picking.shipment.in.scan'
    shipment = fields.Many2One('stock.shipment.in', 'Shipment', readonly=True)
    warehouse_storage = fields.Many2One('stock.location', "Warehouse Storage",
        readonly=True)
    product = fields.Many2One('product.product', 'Product', readonly=True)
    to_location = fields.Many2One('stock.location', 'Location', readonly=True)
    to_pick = fields.Char('To pick')
    pending_inventory_moves = fields.Text("Pending Inventory Moves", readonly=True)


class StockPickingShipmentInResult(ModelView):
    "Stock Picking Shipment In Result"
    __name__ = 'stock.picking.shipment.in.result'
    shipment = fields.Many2One('stock.shipment.in', 'Shipment', readonly=True)
    note = fields.Text('Note', readonly=True)


class StockPickingShipmentIn(Wizard):
    "Stock Picking Shipment In Ask"
    __name__ = 'stock.picking.shipment.in'
    start_state = 'ask'
    ask = StateView('stock.picking.shipment.in.ask',
        'stock_scanner.stock_picking_shipment_in_start', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Scan', 'scan', 'tryton-ok', True),
            ])
    scan = StateView('stock.picking.shipment.in.scan',
        'stock_scanner.stock_picking_shipment_in_scan', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Back', 'ask', 'tryton-back'),
            Button('Reset', 'reset', 'tryton-launch'),
            Button('Pick', 'pick', 'tryton-launch', True),
            Button('Done', 'done', 'tryton-ok'),
            ])
    pick = StateTransition()
    reset = StateTransition()
    done = StateTransition()
    result = StateView('stock.picking.shipment.in.result',
        'stock_scanner.stock_picking_shipment_in_result', [
            Button('Start', 'ask', 'tryton-back', True),
            Button('Exit', 'end', 'tryton-ok'),
            ])

    def transition_reset(self):
        pool = Pool()
        Shipment = pool.get('stock.shipment.in')

        if self.scan.shipment:
            shipment = Shipment(self.scan.shipment)
            shipment.scanned_product = None
            shipment.scanned_quantity = None
            shipment.save()
        self.scan.product = None
        self.scan.to_location = None
        return 'scan'

    def transition_pick(self):
        pool = Pool()
        Shipment = pool.get('stock.shipment.in')
        Location = pool.get('stock.location')
        Move = pool.get('stock.move')
        Warning = Pool().get('res.user.warning')

        shipment = Shipment(self.scan.shipment)

        def qty(value):
            try:
                return float(value)
            except ValueError:
                return False

        shipment = Shipment(self.scan.shipment)
        to_pick = self.scan.to_pick
        quantity = qty(to_pick)

        if self.scan.product:
            if self.scan.to_location and len(to_pick) < 5 and quantity:
                shipment.scanned_product = self.scan.product
                shipment.scanned_quantity = shipment.scanned_uom.round(quantity)
                shipment.save()
                Shipment.scan_inventory([shipment])
                shipment = Shipment(shipment.id)
                # reset in case has not pending moves by product
                if not any(move for move in shipment.pending_inventory_moves if move.product == self.scan.product):
                    self.scan.product = None
                    self.scan.to_location = None
            else:
                loc_to_picks = Location.search([
                    ('rec_name', '=', to_pick),
                    ('parent', 'child_of', self.scan.shipment.warehouse_storage),
                    ('type', 'not in', ['warehouse', 'view']),
                    ], limit=1)
                if not loc_to_picks:
                    raise UserError(gettext('stock_scanner.msg_not_found_location',
                        name=to_pick))

                to_location, = loc_to_picks
                self.scan.to_location = to_location

                # check to_location pick and to_location move
                for move in shipment.pending_inventory_moves:
                    if move.matches_scan(self.scan.product.code):
                        if move.to_location != to_location:
                            if move.quantity == move.pending_quantity:
                                move.to_location = to_location
                                move.save()
                            elif move.quantity > move.pending_quantity:
                                pending_quantity = move.pending_quantity
                                move.quantity = move.quantity - pending_quantity
                                move.save()
                                Move.copy([move], default={'to_location': to_location, 'quantity': pending_quantity})
                            # key = 'picking_change_location.%d' % move.id
                            # if Warning.check(key):
                            #     raise UserWarning(key, gettext(
                            #         'stock_scanner.msg_picking_change_location',
                            #         product=shipment.scanned_product.rec_name,
                            #         location=to_location.rec_name))
                            #     break
        else:
            for move in shipment.pending_inventory_moves:
                if move.matches_scan(to_pick):
                    self.scan.product = move.product
                    self.scan.to_location = move.to_location
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
                    self.scan.to_location = None

        return 'scan'

    def transition_done(self):
        pool = Pool()
        Shipment = pool.get('stock.shipment.in')

        shipment = Shipment(self.scan.shipment)
        Shipment.done([shipment])

        return 'result'

    def default_ask(self, fields):
        # reset values in case start first step (select a shipment)
        self.scan.shipment = None
        self.scan.warehouse_storage = None
        self.scan.product = None
        self.scan.to_location = None
        self.scan.to_pick = None
        self.scan.pending_inventory_moves = None
        return {}

    def default_scan(self, fields):
        pool = Pool()
        Shipment = pool.get('stock.shipment.in')
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
                ('state', '=', 'received'),
                ('number', '=', self.ask.shipment),
                ], limit=1)
            if not shipments:
                return {}
            shipment, = shipments

        # reset scanned_product and scanned_quantity
        if (not self.scan.product and (shipment.scanned_product or shipment.scanned_quantity)):
            shipment.scanned_product = None
            shipment.scanned_quantity = None
            shipment.save()

        defaults = {}
        defaults['shipment'] = shipment.id
        defaults['warehouse_storage'] = shipment.warehouse.storage_location.id
        if hasattr(self.scan, 'product'):
            defaults['product'] = self.scan.product and self.scan.product.id
        if hasattr(self.scan, 'to_location'):
            defaults['to_location'] = self.scan.to_location and self.scan.to_location.id

        pending_inventory_moves = []
        locations_move = {}
        for move in shipment.pending_inventory_moves:
            locations_move.setdefault(move.to_location, [])
            locations_move[move.to_location].append(move)

        for location in sorted(locations_move, key=lambda x: x.name):
            for move in locations_move[location]:
                pending_inventory_moves.append(
                    u'<div align="left">'
                    '<font size="4">{} <b>{}</b> | {}</font>'
                    '</div>'.format(move.pending_quantity,
                        move.product.rec_name, move.to_location.rec_name))
        defaults['pending_inventory_moves'] = '\n'.join(pending_inventory_moves)
        return defaults

    def default_result(self, fields):
        defaults = {}
        defaults['shipment'] = self.scan.shipment and self.scan.shipment.id
        return defaults


class StockPickingShipmentOutAsk(ModelView):
    'Stock Picking Shipment Out Ask'
    __name__ = 'stock.picking.shipment.out.ask'
    shipment = fields.Char("Shipment")
    to_pick = fields.Selection('get_to_pick', "To Pick", sort=True)

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
    shipment = fields.Many2One('stock.shipment.out', "Shipment", readonly=True)
    product = fields.Many2One('product.product', "Product", readonly=True)
    to_pick = fields.Char("To pick")
    pending_moves = fields.Text("Pending Moves", readonly=True)


class StockPickingShipmentOutResult(ModelView):
    "Stock Picking Shipment Out Result"
    __name__ = 'stock.picking.shipment.out.result'
    shipment = fields.Many2One('stock.shipment.out', "Shipment", readonly=True)
    note = fields.Text("Note", readonly=True)


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
            Button('Exit', 'end', 'tryton-ok'),
            ])

    def transition_pick(self):
        pool = Pool()
        Shipment = pool.get('stock.shipment.out')

        shipment = Shipment(self.scan.shipment)

        def qty(value):
            try:
                return float(value)
            except ValueError:
                return False

        shipment = Shipment(self.scan.shipment)
        to_pick = self.scan.to_pick
        quantity = qty(to_pick)

        if self.scan.product and quantity and len(to_pick) < 5:
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

        shipment = Shipment(self.scan.shipment)
        Shipment.assign([shipment])
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

        # reset scanned_product and scanned_quantity
        if (not self.scan.product and (shipment.scanned_product or shipment.scanned_quantity)):
            shipment.scanned_product = None
            shipment.scanned_quantity = None
            shipment.save()

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
