# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.pool import Pool
from trytond.i18n import gettext
from trytond.exceptions import UserWarning


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
    pending_moves = fields.Text("Pending Moves", readonly=True)


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
            Button('Pick', 'pick', 'tryton-launch', True),
            Button('Replenish', 'replenish', 'tryton-ok'),
            ])
    pick = StateTransition()
    replenish = StateTransition()
    result = StateView('stock.picking.shipment.in.result',
        'stock_scanner.stock_picking_shipment_in_result', [
            Button('Start', 'ask', 'tryton-back', True),
            Button('Done', 'end', 'tryton-ok'),
            ])

    def transition_pick(self):
        pool = Pool()
        Shipment = pool.get('stock.shipment.in')
        Location = pool.get('stock.location')
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

        if shipment.scanned_product:
            self.scan.product = shipment.scanned_product
            if self.scan.to_location and quantity and len(to_pick) < 5:
                # TODO picking en blocs, una quantitat en una ubicacio i unes altres quantitats en unes altres ubicacions
                shipment.scanned_quantity = shipment.scanned_uom.round(quantity)
                shipment.save()
                Shipment.scan([shipment])
                shipment = Shipment(shipment.id)
            else:
                # TODO find locations childs of warehouse_storage
                # TODO how to find location? code, name?
                loc_to_picks = Location.search([
                    ('rec_name', '=', to_pick),
                    ], limit=1)
                if loc_to_picks:
                    to_location, = loc_to_picks
                    self.scan.to_location = to_location

                    # check to_location pick and to_location move
                    for move in shipment.pending_moves:
                        if move.matches_scan(shipment.scanned_product.code):
                            if move.to_location != to_location:
                                # TODO com fem el key vagi canviant el ID, sempre ens ho demani (ex. fer picking de unitats en blocs)
                                key = 'picking_change_location.%d' % move.id
                                if Warning.check(key):
                                    raise UserWarning(key, gettext(
                                        'stock_scanner.msg_picking_change_location',
                                        product=shipment.scanned_product.rec_name,
                                        location=to_location.rec_name))
                                    # TODO write to_location in current move
                                    break

                # locations = Location.search([
                #     ('parent', 'child_of', self.scan.warehouse_storage),
                #     ])
                # if locations:
                #     loc_to_picks = Location.search([
                #         ('rec_name', '=', to_pick),
                #         ('id', 'in', [self.scan.warehouse_storage.id] + [l.id for l in locations]),
                #         ], limit=1)
                #     if loc_to_picks:
                #         self.scan.location = loc_to_picks[0].id

        else:
            for move in shipment.pending_moves:
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

    def transition_replenish(self):
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
        self.scan.pending_moves = None
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

        defaults = {}
        defaults['shipment'] = shipment.id
        defaults['warehouse_storage'] = shipment.warehouse.storage_location.id
        if hasattr(self.scan, 'product'):
            defaults['product'] = self.scan.product and self.scan.product.id
        if hasattr(self.scan, 'to_location'):
            defaults['to_location'] = self.scan.to_location and self.scan.to_location.id

        pending_moves = []
        locations_move = {}
        for move in shipment.pending_moves:
            locations_move.setdefault(move.to_location, [])
            locations_move[move.to_location].append(move)

        for location in sorted(locations_move, key=lambda x: x.name):
            if location not in storage_locations:
                pending_moves.append(
                    u'<div align="left">'
                    '<font size="4"><u><b>{}</b></u></font>'
                    '</div>'.format(location.name))
            for move in locations_move[location]:
                pending_moves.append(
                    u'<div align="left">'
                    '<font size="4">{} <b>{}</b> | {}</font>'
                    '</div>'.format(move.pending_quantity,
                        move.product.rec_name, move.to_location.rec_name))
        defaults['pending_moves'] = '\n'.join(pending_moves)
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
            Button('Done', 'end', 'tryton-ok'),
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

        if shipment.scanned_product and quantity and len(to_pick) < 5:
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
