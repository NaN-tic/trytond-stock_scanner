# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import stock
from . import picking


def register():
    Pool.register(
        stock.Configuration,
        stock.Move,
        stock.ShipmentIn,
        stock.ShipmentOut,
        stock.ShipmentOutReturn,
        picking.StockPickingShipmentOutAsk,
        picking.StockPickingShipmentOutScan,
        picking.StockPickingShipmentOutResult,
        module='stock_scanner', type_='model')
    Pool.register(
        picking.StockPickingShipmentOut,
        module='stock_scanner', type_='wizard')