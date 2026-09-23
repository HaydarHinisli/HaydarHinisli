from ..modelle import Plattform
from .basis import Abgebrochen, NichtAngemeldet, PlattformBasis, PlattformFehler, Statistik, Veroeffentlicht
from .kleinanzeigen import Kleinanzeigen
from .vinted import Vinted

KLASSEN: dict[Plattform, type[PlattformBasis]] = {
    Plattform.kleinanzeigen: Kleinanzeigen,
    Plattform.vinted: Vinted,
}

__all__ = ["KLASSEN", "Abgebrochen", "NichtAngemeldet", "PlattformBasis", "PlattformFehler", "Statistik", "Veroeffentlicht"]
