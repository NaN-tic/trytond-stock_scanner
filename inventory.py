# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.pool import Pool
from trytond.pyson import Eval
from trytond.exceptions import UserError
from trytond.i18n import gettext


class StockScannerInventoryAsk(ModelView):
    'Stock Scanner Inventory Ask'
    __name__ = 'stock.scanner.inventory.ask'
    from_location = fields.Many2One('stock.location', "From Location",
        domain=[
            ('type', 'in', ['lost_found', 'storage']),
        ], required=True)
    to_location = fields.Many2One('stock.location', "To Location",
        domain=[
            ('type', 'in', ['lost_found', 'storage']),
        ], required=True)
    to_inventory = fields.Selection([
        ('complete', 'Complete'),
        ('products', 'Products'),
        ], 'To Pick', required=True)

    @staticmethod
    def default_to_inventory():
        return 'products'


class StockScannerInventoryScan(ModelView):
    'Stock Scanner Inventory Scan'
    __name__ = 'stock.scanner.inventory.scan'
    from_location = fields.Many2One('stock.location', "From Location",
        domain=[
            ('type', 'in', ['lost_found', 'storage']),
        ], readonly=True)
    to_location = fields.Many2One('stock.location', "To Location",
        domain=[
            ('type', 'in', ['lost_found', 'storage']),
        ], readonly=True)
    product = fields.Many2One('product.product', "Product", readonly=True)
    to_pick = fields.Char("To pick")
    lines = fields.One2Many('stock.scanner.inventory.line', None, "Lines")


class StockScannerInventoryLine(ModelView):
    'Stock Scanner Inventory Line'
    __name__ = 'stock.scanner.inventory.line'
    product = fields.Many2One('product.product', "Product")
    product_uom_category = fields.Function(
        fields.Many2One('product.uom.category', "Product Uom Category"),
        'on_change_with_product_uom_category')
    uom = fields.Many2One("product.uom", "Uom", required=True,
        domain=[
            ('category', '=', Eval('product_uom_category')),
            ],
        depends=['state', 'unit_price', 'product_uom_category'],
        help="The unit in which the quantity is specified.")
    unit_digits = fields.Function(fields.Integer("Unit Digits"),
        'on_change_with_unit_digits')
    quantity = fields.Float("Quantity", required=True,
        digits=(16, Eval('unit_digits', 2)),
        depends=['unit_digits'])

    @fields.depends('product', 'uom')
    def on_change_product(self):
        if self.product:
            if (not self.uom
                    or self.uom.category != self.product.default_uom.category):
                self.uom = self.product.default_uom
                self.unit_digits = self.product.default_uom.digits

    @fields.depends('product')
    def on_change_with_product_uom_category(self, name=None):
        if self.product:
            return self.product.default_uom_category.id

    @fields.depends('uom')
    def on_change_with_unit_digits(self, name=None):
        if self.uom:
            return self.uom.digits
        return 2


class StockScannerInventoryResult(ModelView):
    "Stock Scanner Inventory Result"
    __name__ = 'stock.scanner.inventory.result'
    inventory = fields.Many2One('stock.inventory', "Inventory", readonly=True)


class StockScannerInventory(Wizard):
    "Stock Scanner Inventory Ask"
    __name__ = 'stock.scanner.inventory'
    start_state = 'ask'
    ask = StateView('stock.scanner.inventory.ask',
        'stock_scanner.stock_scanner_inventory_start', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Scan', 'scan', 'tryton-ok', True),
            ])
    scan = StateView('stock.scanner.inventory.scan',
        'stock_scanner.stock_scanner_inventory_scan', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Back', 'ask', 'tryton-back'),
            Button('Pick', 'pick', 'tryton-launch', True),
            Button('Done', 'done', 'tryton-ok'),
            ])
    pick = StateTransition()
    packed = StateTransition()
    result = StateView('stock.scanner.inventory.result',
        'stock_scanner.stock_scanner_inventory_result', [
            Button('Start', 'ask', 'tryton-back', True),
            Button('Done', 'end', 'tryton-ok'),
            ])

    def transition_pick(self):
        pool = Pool()
        StockScannerInventoryLine = pool.get('stock.scanner.inventory.line')
        Product = pool.get('product.product')

        # pool = Pool()
        # Shipment = pool.get('stock.shipment.out')
        #
        # shipment = Shipment(self.scan.shipment)

        def qty(value):
            try:
                return float(value)
            except ValueError:
                return False

        # shipment = Shipment(self.scan.shipment)
        to_pick = self.scan.to_pick
        quantity = qty(to_pick)

        if self.scan.product and len(to_pick) < 5 and quantity:
            for line in self.scan.lines:
                if line.product == self.scan.product:
                    line.quantity = quantity
            # shipment.scanned_quantity = shipment.scanned_uom.round(quantity)
            # shipment.save()
            # Shipment.scan([shipment])StockScannerInventory
            # shipment = Shipment(shipment.id)
        else:
            products = Product.search([
                ('rec_name', '=', to_pick),
                ], limit=1)
            if products:
                product, = products
                products = set([line.product for line in self.scan.lines])

                if product not in products:
                    line = StockScannerInventoryLine()
                    line.product = product
                    line.on_change_product()

                    add_line = {
                        'product': product.id,
                        'uom': line.uom.id,
                        'unit_digits': line.unit_digits,
                        'product_uom_category': line.on_change_with_product_uom_category(),
                        'quantity': 0,
                        }
                    self.scan.lines += (add_line,)

                self.scan.product = product
            else:
                self.scan.product = None
                self.scan.to_pick = None
        return 'scan'

    def transition_done(self):
        pool = Pool()
        # Shipment = pool.get('stock.shipment.out')
        #
        # shipment = Shipment(self.scan.shipment)
        # Shipment.assign([shipment])
        # Shipment.pack([shipment])

        return 'result'

    def default_ask(self, fields):
        # reset values in case start first step (select a shipment)
        self.scan.product = None
        self.scan.to_pick = None
        # self.scan.lines = None
        return {}

    def default_scan(self, fields):
        from_location = self.ask.from_location
        to_location = self.ask.to_location

        # control are lost_found and storage location type
        if len(set((from_location.type, to_location.type))) != 2:
            # self.ask.from_location = None
            # self.ask.to_location = None
            raise UserError(
                gettext('stock_scanner.msg_scan_inventory_location'))

        defaults = {}
        defaults['from_location'] = from_location.id
        defaults['to_location'] = to_location.id

        if hasattr(self.scan, 'product'):
            defaults['product'] = self.scan.product and self.scan.product.id
        if hasattr(self.scan, 'lines'):
            defaults['lines'] = [{
                'product': line.product.id,
                'uom': line.uom.id,
                'unit_digits': line.unit_digits,
                'quantity': line.quantity,
                'product_uom_category': line.product_uom_category.id,
                } for line in self.scan.lines]
        return defaults

    def default_result(self, fields):
        defaults = {}
        # defaults['inventory'] = self.scan.shipment and self.scan.shipment.id
        return defaults
