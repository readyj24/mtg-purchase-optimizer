from pydantic import BaseModel
from typing import Optional


class CardPrinting(BaseModel):
    scryfall_id: str
    card_name: str
    set_code: str
    set_name: str
    collector_number: str
    foil: bool
    image_uri: Optional[str] = None
    released_at: str
    rarity: str
    tcg_price: Optional[float] = None  # TCGPlayer reference price from Scryfall


class StorePrice(BaseModel):
    store_id: str   # "card_kingdom" | "star_city_games" | "tcgplayer" | "tcgplayer_direct"
    store_name: str
    price: Optional[float] = None
    quantity: Optional[int] = None
    url: Optional[str] = None
    condition: Optional[str] = None
    error: Optional[str] = None


class PrintingWithPrices(BaseModel):
    printing: CardPrinting
    store_prices: list[StorePrice] = []


class ParsedCard(BaseModel):
    original_text: str
    card_name: str
    quantity: int
    set_hint: Optional[str] = None


class CardListParseRequest(BaseModel):
    text: str


class PriceRequest(BaseModel):
    card_name: str
    set_code: str
    set_name: str
    collector_number: str
    foil: bool


class AcceptedPrinting(BaseModel):
    printing: CardPrinting
    store_prices: list[StorePrice]


class CardSelection(BaseModel):
    card_name: str
    quantity: int
    accepted_printings: list[AcceptedPrinting]


class OptimizeRequest(BaseModel):
    cards: list[CardSelection]


class CartItem(BaseModel):
    card_name: str
    quantity: int
    set_name: str
    set_code: str
    foil: bool
    price_each: float
    total_price: float
    url: Optional[str] = None


class OptimizeResult(BaseModel):
    carts: dict[str, list[CartItem]]
    cart_totals: dict[str, float]
    store_names: dict[str, str]
    missing_cards: list[str]
