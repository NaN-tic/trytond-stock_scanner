#This file is part stock_valued module for Tryton.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
from trytond.pool import Pool
from .stock import *


def register():
    Pool.register(
#        CompanyScannerInputReports,
#        CompanyScannerOutputReports,
        Configuration,
        Move,
        ShipmentIn,
        ShipmentInReturn,
        ShipmentOut,
        ShipmentOutReturn,
        Product,
        ProductSupplier,
        module='stock_scanner', type_='model')
