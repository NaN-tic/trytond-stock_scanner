===========================
Stock Shipment Out Scenario
===========================

=============
General Setup
=============

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from proteus import config, Model, Wizard
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts, create_tax
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> from trytond.tests.tools import activate_modules
    >>> today = datetime.date.today()

Install product_cost_plan Module::

    >>> config = activate_modules('stock_scanner')


Create company::

    >>> _ = create_company()
    >>> company = get_company()
    >>> party = company.party

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')
    >>> period = fiscalyear.periods[0]

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> receivable = accounts['receivable']
    >>> payable = accounts['payable']
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> account_tax = accounts['tax']
    >>> account_cash = accounts['cash']

Create customer::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name='Customer')
    >>> customer.save()

Create category::

    >>> ProductCategory = Model.get('product.category')
    >>> account_category = ProductCategory(name='Category')
    >>> account_category.accounting = True
    >>> account_category.account_expense = expense
    >>> account_category.account_revenue = revenue
    >>> account_category.save()

Create product::

    >>> ProductUom = Model.get('product.uom')
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> product = Product()
    >>> template = ProductTemplate()
    >>> template.name = 'Product'
    >>> template.account_category = account_category
    >>> template.default_uom = unit
    >>> template.type = 'goods'
    >>> template.list_price = Decimal('20')
    >>> template.salable = True
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Configure stock::

    >>> StockConfig = Model.get('stock.configuration')
    >>> stock_config = StockConfig(1)
    >>> stock_config.scanner_on_shipment_in = True
    >>> stock_config.scanner_on_shipment_in_return = True
    >>> stock_config.scanner_on_shipment_out = True
    >>> stock_config.scanner_on_shipment_out_return = True
    >>> stock_config.scanner_fill_quantity = True
    >>> stock_config.save()

Get stock locations::

    >>> Location = Model.get('stock.location')
    >>> storage_loc, = Location.find([('code', '=', 'STO')])

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Create a sale::

    >>> Sale = Model.get('sale.sale')
    >>> sale = Sale()
    >>> sale.party = customer
    >>> sale.payment_term = payment_term
    >>> sale.invoice_method = 'order'
    >>> sale_line = sale.lines.new()
    >>> sale_line.product = product
    >>> sale_line.quantity = 10
    >>> sale.save()
    >>> sale.click('quote')
    >>> sale.click('confirm')
    >>> sale.click('process')

There is a shipment waiting::

    >>> shipment_out, = sale.shipments
    >>> len(shipment_out.outgoing_moves)
    1
    >>> len(shipment_out.inventory_moves)
    1
    >>> len(shipment_out.pending_moves)
    1
    >>> move, = shipment_out.pending_moves
    >>> move.pending_quantity
    10.0

Make 1 unit of the product available::

    >>> Inventory = Model.get('stock.inventory')
    >>> inventory = Inventory()
    >>> inventory.location = storage_loc
    >>> inventory_line = inventory.lines.new()
    >>> inventory_line.product = product
    >>> inventory_line.quantity = 1
    >>> inventory_line.expected_quantity = 0.0
    >>> inventory.click('confirm')
    >>> inventory.state
    'done'

Scan one unit of the shipment and assign it::

    >>> shipment_out.click('assign_try')
    >>> shipment_out.reload()
    >>> move, _ = sorted(shipment_out.pending_moves, key=lambda x: x.quantity)
    >>> move.quantity == 1.0
    True
    >>> move.pending_quantity == 1.0
    True
    >>> shipment_out.scanned_product = product
    >>> shipment_out.scanned_quantity = 1.0
    >>> shipment_out.click('scan')
    >>> shipment_out.reload()
    >>> move.reload()
    >>> move.scanned_quantity == 1.0
    True
    >>> move.pending_quantity == 0.0
    True
    >>> shipment_out.scanned_product == None
    True
    >>> shipment_out.reload()
    >>> len(shipment_out.outgoing_moves)
    1
    >>> len(shipment_out.inventory_moves)
    2
    >>> move, _ = sorted(shipment_out.inventory_moves, key=lambda x: x.quantity)
    >>> move.pending_quantity == 0.0
    True
    >>> move.quantity == 1.0
    True
    >>> move, = shipment_out.outgoing_moves
    >>> move.quantity == 10.0
    True

    >>> shipment_out.scanned_product = product
    >>> shipment_out.scanned_quantity = 9.0
    >>> shipment_out.click('scan')
    >>> shipment_out.reload()
    >>> shipment_out.pending_moves == []
    True

Set the state as Done::

    >>> shipment_out.click('pick')
    >>> shipment_out.click('pack')
    >>> move, _ = sorted(shipment_out.inventory_moves, key=lambda x: x.quantity)
    >>> shipment_out.click('do')
    >>> len(shipment_out.outgoing_moves)
    1
    >>> len(shipment_out.inventory_moves)
    2
    >>> shipment_out.inventory_moves[0].state
    'done'
    >>> shipment_out.outgoing_moves[0].state
    'done'
    >>> sum([m.quantity for m in shipment_out.inventory_moves]) == \
    ...     sum([m.quantity for m in shipment_out.outgoing_moves])
    True
