# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import stock


def register():
    Pool.register(
        stock.Configuration,
        stock.Move,
        stock.ShipmentIn,
        stock.ShipmentInReturn,
        stock.ShipmentOut,
        stock.ShipmentOutReturn,
        module='stock_scanner', type_='model')
