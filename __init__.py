# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from .stock import *


def register():
    Pool.register(
        Configuration,
        Move,
        ShipmentIn,
        ShipmentOut,
        ShipmentOutReturn,
        module='stock_scanner', type_='model')
