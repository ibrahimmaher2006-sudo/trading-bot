"""Thin wrapper around ib_async: connect to IBKR and place market orders."""

from ib_async import IB, Stock, MarketOrder


class IBKRClient:
    def __init__(self, host, port, client_id):
        self.ib = IB()
        self.ib.connect(host, port, clientId=client_id)

    def place_order(self, symbol, side, quantity):
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        order = MarketOrder(side, quantity, outsideRth=True)
        trade = self.ib.placeOrder(contract, order)

        # Wait up to 10s for the order to settle past the transient pending states.
        for _ in range(10):
            self.ib.sleep(1)
            if trade.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                break
        return trade

    def disconnect(self):
        self.ib.disconnect()