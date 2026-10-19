import re
import unicodedata

from onboarding.llm.client import FallbackLLM
from onboarding.metrics import llm_flags
from onboarding.models import OnboardingState, Status, mask_document_id
from onboarding.policies import PRODUCTS

SYSTEM = ("Eres el asistente de onboarding de un banco ecuatoriano. Redacta un mensaje breve (máx. 120 "
          "palabras), cordial y en español para el cliente. NO cambies la decisión ni inventes requisitos: "
          "usa solo los hechos dados. No menciones listas de sanciones ni detalles internos de riesgo.")

LLM_MAX_CHARS = 800

# Línea fija determinista: el cliente siempre lee el estado real, independientemente del LLM.
STATUS_LINE = {
    Status.APPROVED: "Aprobada",
    Status.APPROVED_WITH_CONDITIONS: "Aprobada con condiciones",
    Status.ESCALATED: "En revisión",
    Status.REJECTED: "No aprobada",
    Status.IN_PROGRESS: "En proceso",
}

# Texto ya normalizado (minúsculas, sin tildes). Las negaciones se quitan antes de buscar aprobación.
_NEGATED_APPROVAL = re.compile(r"\bno\s+(?:fue\s+|ha\s+sido\s+|sera\s+|puede\s+ser\s+)?aprobad\w*")
_APPROVAL = re.compile(r"aprobad|approved|felicidades|bienvenid")
_REJECTION = re.compile(r"rechaz|denegad|\bno\s+(?:fue\s+|ha\s+sido\s+)?aprobad|rejected")


_DOCUMENT_ID = re.compile(r"\d{10}")


def first_name(s: OnboardingState) -> str:
    return s.prospect.prospect_name.split()[0]


def scrub_pii(s: OnboardingState, text: str) -> str:
    """LOPDP (RNF-09): lo que sale hacia un proveedor LLM externo no lleva cédula ni apellidos del prospecto.

    Se aplica al prompt completo porque campos de texto libre (p. ej. `product`) también llegan al LLM.
    """
    text = _DOCUMENT_ID.sub(lambda m: mask_document_id(m.group()), text)
    for surname in s.prospect.prospect_name.split()[1:]:
        text = re.sub(rf"\b{re.escape(surname)}\b", f"{surname[0].upper()}.", text, flags=re.IGNORECASE)
    return text


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def contradiction(status: Status, text: str) -> str | None:
    """Motivo por el que el texto del LLM contradice la decisión determinista, o None si es coherente."""
    norm = _normalize(text)
    if status in (Status.REJECTED, Status.ESCALATED, Status.IN_PROGRESS):
        if _APPROVAL.search(_NEGATED_APPROVAL.sub(" ", norm)):
            return "approval_terms_in_non_approved"
    elif _REJECTION.search(norm):
        return "rejection_terms_in_approved"
    return None


class ResponseAgent:
    """Sin tools: solo redacta. La decisión ya fue tomada por el motor de políticas."""

    name = "ResponseAgent"

    def __init__(self, llm: FallbackLLM) -> None:
        self.llm = llm

    def status_line(self, s: OnboardingState) -> str:
        return f"Estado de tu solicitud: {STATUS_LINE.get(s.status, 'En proceso')}"

    def template(self, s: OnboardingState) -> str:
        name = first_name(s)
        product = PRODUCTS.get(s.prospect.product, {}).get("name", s.prospect.product)
        docs = "; ".join(s.required_documents)
        match s.status:
            case Status.APPROVED:
                return f"Hola {name}, tu solicitud de {product} fue aprobada. Para continuar, carga: {docs}."
            case Status.APPROVED_WITH_CONDITIONS:
                return (f"Hola {name}, tu solicitud de {product} fue aprobada con condiciones. "
                        f"Necesitamos estos documentos: {docs}.")
            case Status.ESCALATED:
                return (f"Hola {name}, estamos revisando tu solicitud de {product} con un especialista. "
                        "Te contactaremos en un máximo de 48 horas.")
            case _:
                return (f"Hola {name}, por ahora no podemos continuar con tu solicitud de {product}. "
                        f"Te sugerimos: {s.proposals[-1] if s.proposals else 'acercarte a una agencia'}.")

    def _validate(self, s: OnboardingState, text: str | None) -> str | None:
        """Guardrail: descarta la salida del LLM si es demasiado larga o contradice la decisión."""
        if not text:
            return None
        reason = "too_long" if len(text) > LLM_MAX_CHARS else contradiction(s.status, text)
        if reason:
            s.log(self.name, "llm_output_rejected", provider=self.llm.last_provider, reason=reason,
                  status=s.status.value)
            return None
        return text

    def run(self, s: OnboardingState) -> str:
        facts = {"nombre": first_name(s), "producto": s.prospect.product, "estado": s.status.value,
                 "documentos_requeridos": s.required_documents,
                 "siguiente_paso_para_cliente": s.proposals[-1] if s.proposals else None}
        raw = self.llm.complete(SYSTEM, scrub_pii(s, f"Hechos: {facts}"))
        body = self._validate(s, raw)
        provider = self.llm.last_provider if body else "template"
        s.log(self.name, "message_generated", provider=provider, **llm_flags(self.llm, raw, provider))
        return f"{self.status_line(s)}\n{body or self.template(s)}"
