"""Cart optimization logic.

Given a list of cards (each with a set of accepted printings that carry
store prices), produce an optimized shopping cart that minimises total
cost while fulfilling all quantities.

The algorithm is a simple greedy: for each card sort all available
(printing, store, price) options by price ascending, then take from the
cheapest options until the required quantity is satisfied.

Future enhancements could include:
- Minimising the number of stores (to reduce shipping costs).
- Per-store "buy everything here" mode.
- Integer linear programming for true optimality.
"""

from models import CartItem, OptimizeRequest, OptimizeResult

STORE_NAMES = {
    "card_kingdom": "Card Kingdom",
    "star_city_games": "Star City Games",
    "channel_fireball": "Channel Fireball",
}


def optimize_cart(request: OptimizeRequest) -> OptimizeResult:
    carts: dict[str, list[CartItem]] = {sid: [] for sid in STORE_NAMES}
    missing: list[str] = []

    for card_sel in request.cards:
        card_name = card_sel.card_name
        qty_needed = card_sel.quantity

        # Gather all (printing, store, price, qty_avail, url) options
        options = []
        for ap in card_sel.accepted_printings:
            printing = ap.printing
            for sp in ap.store_prices:
                if sp.price is None or sp.price <= 0:
                    continue
                qty_avail = sp.quantity if sp.quantity is not None else 999
                if qty_avail <= 0:
                    continue
                options.append(
                    {
                        "printing": printing,
                        "store_id": sp.store_id,
                        "price": sp.price,
                        "qty_avail": qty_avail,
                        "url": sp.url,
                    }
                )

        if not options:
            missing.append(card_name)
            continue

        # Sort cheapest first
        options.sort(key=lambda o: o["price"])

        qty_remaining = qty_needed
        for opt in options:
            if qty_remaining <= 0:
                break
            take = min(qty_remaining, opt["qty_avail"])
            printing = opt["printing"]
            carts[opt["store_id"]].append(
                CartItem(
                    card_name=card_name,
                    quantity=take,
                    set_name=printing.set_name,
                    set_code=printing.set_code,
                    foil=printing.foil,
                    price_each=opt["price"],
                    total_price=round(take * opt["price"], 2),
                    url=opt["url"],
                )
            )
            qty_remaining -= take

        if qty_remaining > 0:
            label = card_name
            if qty_remaining < qty_needed:
                label = f"{card_name} ({qty_remaining} of {qty_needed} unfulfilled)"
            missing.append(label)

    cart_totals = {
        sid: round(sum(item.total_price for item in items), 2)
        for sid, items in carts.items()
    }

    return OptimizeResult(
        carts=carts,
        cart_totals=cart_totals,
        store_names=STORE_NAMES,
        missing_cards=missing,
    )
