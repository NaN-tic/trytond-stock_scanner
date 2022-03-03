# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.pool import Pool
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.pyson import Bool, Eval


class StockScannerInventoryAsk(ModelView):
    'Stock Scanner Inventory Ask'
    __name__ = 'stock.scanner.inventory.ask'
    inventory = fields.Many2One('stock.inventory', "Inventory", domain=[
        ('state', '=', 'draft'),
        ])
    location = fields.Many2One('stock.location', "Location",
        domain=[
            ('type', '=', 'storage'),
        ], states={
            'invisible': Bool(Eval('inventory')),
            'required': ~Bool(Eval('inventory')),
        }, depends=['inventory'])
    lost_found = fields.Many2One('stock.location', "Lost and Found",
        domain=[
            ('type', '=', 'lost_found'),
        ], states={
            'invisible': Bool(Eval('inventory')),
            'required': ~Bool(Eval('inventory')),
        }, depends=['inventory'])
    to_inventory = fields.Selection([
        ('complete', 'Complete'),
        ('products', 'Products'),
        ], "To Pick",
        states={
            'invisible': Bool(Eval('inventory')),
            'required': ~Bool(Eval('inventory')),
        }, depends=['inventory'])
    empty_quantity = fields.Selection([
        ('keep', "Keep"),
        ('empty', "Empty"),
        ], "Empty Quantity", states={
            'invisible': (
                (Eval('to_inventory') != 'complete') | Bool(Eval('inventory'))),
            'required': Eval('to_inventory') == 'complete'
        }, depends=['to_inventory', 'inventory'])

    @staticmethod
    def default_to_inventory():
        return 'products'

    @staticmethod
    def default_empty_quantity():
        return 'empty'


class StockScannerInventoryScan(ModelView):
    'Stock Scanner Inventory Scan'
    __name__ = 'stock.scanner.inventory.scan'
    inventory = fields.Many2One('stock.inventory', "Inventory", readonly=True)
    location = fields.Many2One('stock.location', "Location",
        domain=[
            ('type', '=','storage'),
        ], readonly=True)
    lost_found = fields.Many2One('stock.location', "Lost and Found",
        domain=[
            ('type', '=', 'lost_found'),
        ], readonly=True)
    product = fields.Many2One('product.product', "Product", readonly=True)
    to_pick = fields.Char("To pick")
    lines = fields.Text("Lines", readonly=True)


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
    done = StateTransition()
    result = StateView('stock.scanner.inventory.result',
        'stock_scanner.stock_scanner_inventory_result', [
            Button('Start', 'ask', 'tryton-back', True),
            Button('Done', 'end', 'tryton-ok'),
            ])

    def transition_pick(self):
        pool = Pool()
        InventoryLine = pool.get('stock.inventory.line')
        Product = pool.get('product.product')
        Configuration = pool.get('stock.configuration')

        def qty(value):
            try:
                return float(value)
            except ValueError:
                return False

        config = Configuration(1)
        to_pick = self.scan.to_pick
        quantity = qty(to_pick)

        if self.scan.product and len(to_pick) < 5 and quantity:
            for line in self.scan.inventory.lines:
                if line.product == self.scan.product:
                    line.quantity = quantity
                    line.save()
        else:
            products = Product.search([
                ('rec_name', '=', to_pick),
                ], limit=1)
            if products:
                product, = products
                products = set([line.product for line in self.scan.inventory.lines])

                if product not in products:
                    line = InventoryLine()
                    line.inventory = self.scan.inventory
                    line.product = product
                    line.quantity = 1 if config.scanner_inventory_quantity else 0
                    line.on_change_product()
                    line.save()
                self.scan.product = product
            else:
                self.scan.product = None
                self.scan.to_pick = None
        return 'scan'

    def transition_done(self):
        pool = Pool()
        Inventory = pool.get('stock.inventory')

        Inventory.complete_lines([self.scan.inventory], fill=False)
        Inventory.confirm([self.scan.inventory])

        return 'result'

    def default_ask(self, fields):
        # reset values in case start first step
        self.scan.inventory = None
        self.scan.location = None
        self.scan.lost_found = None
        self.scan.product = None
        self.scan.to_pick = None
        self.scan.lines = None
        return {}

    def default_scan(self, fields):
        pool = Pool()
        Inventory = pool.get('stock.inventory')
        InventoryLine = pool.get('stock.inventory.line')
        Date = pool.get('ir.date')
        Configuration = pool.get('stock.configuration')

        config = Configuration(1)

        inventory = self.ask.inventory
        if inventory:
            location = inventory.location
            lost_found = inventory.lost_found
        else:
            location = self.ask.location
            lost_found = self.ask.lost_found

        # control are lost_found and storage location type
        if len(set((location.type, lost_found.type))) != 2:
            # self.ask.from_location = None
            # self.ask.to_location = None
            raise UserError(
                gettext('stock_scanner.msg_scan_inventory_location'))

        defaults = {}
        defaults['location'] = location.id
        defaults['lost_found'] = lost_found.id

        if hasattr(self.scan, 'inventory') and self.scan.inventory:
            inventory = self.scan.inventory
        elif self.ask.inventory:
             inventory = self.ask.inventory
        else:
            is_complete = True if self.ask.to_inventory == 'complete' else False

            inventory = Inventory()
            inventory.location = location
            inventory.lost_found = lost_found
            inventory.date = Date.today()
            if is_complete:
                inventory.empty_quantity = self.ask.empty_quantity
            inventory.save()
            if is_complete:
                Inventory.complete_lines([inventory])
                lines = inventory.lines
                if lines:
                    quantity = 1 if config.scanner_inventory_quantity else 0
                    InventoryLine.write(list(lines), {'quantity': quantity})

        defaults['inventory'] = inventory.id

        if hasattr(self.scan, 'product'):
            defaults['product'] = self.scan.product and self.scan.product.id

        if hasattr(self.scan, 'lines'):
            defaults['lines'] = [u'<div align="left">'
                '<font size="4">{} <b>{}</b></font>'
                '</div>'.format(line.quantity or 0, line.product.rec_name)
                for line in inventory.lines if ((line.quantity or 0) < line.expected_quantity)]
        return defaults

    def default_result(self, fields):
        defaults = {}
        defaults['inventory'] = self.scan.inventory and self.scan.inventory.id
        return defaults
