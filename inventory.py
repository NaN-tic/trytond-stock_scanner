# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.pool import Pool
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.pyson import Bool, Eval
from trytond.transaction import Transaction


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
    load_complete_lines = fields.Boolean("Load Complete Lines", readonly=True)

    @staticmethod
    def default_to_inventory():
        return 'products'

    @staticmethod
    def default_empty_quantity():
        return 'empty'

    @staticmethod
    def default_load_complete_lines():
        return False

    @staticmethod
    def default_stop_load_complete_lines():
        return False

    @fields.depends('inventory')
    def on_change_inventory(self):
        self.load_complete_lines = True if self.inventory else False

    @fields.depends('to_inventory')
    def on_change_to_inventory(self):
        self.load_complete_lines = True if self.to_inventory == 'complete' else False


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
    complete_lines = fields.One2Many('stock.inventory.line', 'inventory',
        "Complete Lines", readonly=True)
    stop_complete_lines = fields.Boolean("Stop Complete Lines", readonly=True)


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
            Button('', 'end', 'tryton-cancel'),
            Button('', 'ask', 'tryton-back'),
            Button('Pick', 'pick', 'tryton-launch', True),
            Button('', 'done', 'tryton-ok'),
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
                    # remove product from complete_lines
                    if self.scan.complete_lines:
                        lines = list(self.scan.complete_lines)
                        if line in lines:
                            lines.remove(line)
                        if not lines:
                            self.scan.stop_complete_lines = True
                        self.scan.complete_lines = lines
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
                    line.quantity = 0
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
        self.scan.stop_complete_lines = False
        return {}

    def default_scan(self, fields):
        pool = Pool()
        Inventory = pool.get('stock.inventory')
        InventoryLine = pool.get('stock.inventory.line')
        Date = pool.get('ir.date')
        Configuration = pool.get('stock.configuration')
        Product = pool.get('product.product')

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
            inventory_date = Date.today()

            inventory = Inventory()
            inventory.location = location
            inventory.lost_found = lost_found
            inventory.date = inventory_date
            if is_complete:
                inventory.empty_quantity = self.ask.empty_quantity
            inventory.save()
            if is_complete:
                Inventory.complete_lines([inventory])
                lines = inventory.lines

        defaults['inventory'] = inventory.id

        if hasattr(self.scan, 'product'):
            defaults['product'] = self.scan.product and self.scan.product.id

        if hasattr(self.scan, 'lines'):
            if self.scan.stop_complete_lines:
                lines = []
            elif hasattr(self.scan, 'complete_lines') and self.scan.complete_lines:
                lines = self.scan.complete_lines
            else:
                lines = inventory.lines

            defaults['lines'] = [u'<div align="left">'
                '<font size="4">{} <b>{}</b></font>'
                '</div>'.format(line.quantity or '', line.product.rec_name)
                for line in lines]

            # complete inventory do control products that are picked and not show
            if self.ask.load_complete_lines:
                defaults['complete_lines'] = [l.id for l in inventory.lines]
                self.ask.load_complete_lines = False
            elif hasattr(self.scan, 'complete_lines'):
                defaults['complete_lines'] = [l.id for l in self.scan.complete_lines]
                self.ask.load_complete_lines = False

        return defaults

    def default_result(self, fields):
        defaults = {}
        defaults['inventory'] = self.scan.inventory and self.scan.inventory.id
        return defaults
