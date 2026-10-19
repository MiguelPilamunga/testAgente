from onboarding.llm.client import FallbackLLM
from onboarding.models import OnboardingState, Status
from onboarding.policies import PRODUCTS

SYSTEM = ("Eres el asistente de onboarding de un banco ecuatoriano. Redacta un mensaje breve (máx. 120 "
          "palabras), cordial y en español para el cliente. NO cambies la decisión ni inventes requisitos: "
          "usa solo los hechos dados. No menciones listas de sanciones ni detalles internos de riesgo.")


class ResponseAgent:
    """Sin tools: solo redacta. La decisión ya fue tomada por el motor de políticas."""

    name = "ResponseAgent"

    def __init__(self, llm: FallbackLLM) -> None:
        self.llm = llm

    def template(self, s: OnboardingState) -> str:
        name = s.prospect.prospect_name.split()[0]
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

    def run(self, s: OnboardingState) -> str:
        facts = {"nombre": s.prospect.prospect_name, "producto": s.prospect.product, "estado": s.status.value,
                 "documentos_requeridos": s.required_documents,
                 "siguiente_paso_para_cliente": s.proposals[-1] if s.proposals else None}
        msg = self.llm.complete(SYSTEM, f"Hechos: {facts}") or self.template(s)
        s.log(self.name, "message_generated", provider=self.llm.last_provider)
        return msg
