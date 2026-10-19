"""Políticas del banco: única fuente de reglas de aptitud (deterministas y auditables)."""

IDENTITY_MIN_CONFIDENCE = 0.8
TOOL_MAX_ATTEMPTS = 2  # 1 intento + 1 reintento

PRODUCTS: dict[str, dict] = {
    "cuenta_ahorros": {
        "name": "Cuenta de Ahorros",
        "documents": ["Cédula de identidad (ambos lados)", "Planilla de servicio básico (≤3 meses)",
                      "Formulario Conozca a su Cliente (KYC)"],
        "policy_refs": ["POL-KYC-001", "POL-AHO-010"],
    },
    "cuenta_corriente": {
        "name": "Cuenta Corriente",
        "documents": ["Cédula de identidad (ambos lados)", "Planilla de servicio básico (≤3 meses)",
                      "Formulario KYC", "Referencia bancaria", "Certificado de ingresos"],
        "policy_refs": ["POL-KYC-001", "POL-CTE-020"],
    },
    "tarjeta_credito": {
        "name": "Tarjeta de Crédito",
        "documents": ["Cédula de identidad (ambos lados)", "Formulario KYC", "Rol de pagos (3 meses)",
                      "Autorización de consulta al buró de crédito"],
        "policy_refs": ["POL-KYC-001", "POL-TC-030"],
    },
}

ENHANCED_DUE_DILIGENCE_DOCS = ["Declaración jurada de origen lícito de fondos",
                               "Formulario de Persona Expuesta Políticamente (PEP)"]

# Catálogo de mitigaciones: la propuesta base nunca depende del LLM.
MITIGATIONS = {
    "identity_ambiguous": "Confianza de identidad bajo umbral: solicitar re-validación biométrica "
                          "(selfie + prueba de vida) o revisión manual por un oficial de cumplimiento.",
    "identity_failed": "Identidad no coincide con Registro Civil: invitar al cliente a verificación "
                       "presencial en agencia con cédula original.",
    "risk_high": "Coincidencia en listas de riesgo alto: escalar a Cumplimiento para debida diligencia "
                 "reforzada y confirmar/descartar homonimia antes de cualquier aprobación.",
    "risk_medium": "Riesgo medio: aprobar con condiciones solicitando documentos de debida diligencia "
                   "reforzada y monitoreo transaccional intensificado.",
    "tool_unavailable": "Servicio de verificación no disponible tras reintento: reintentar más tarde "
                        "(acción 'retry') o continuar con verificación manual.",
    "product_unknown": "Producto no ofertado: ofrecer productos disponibles: " + ", ".join(PRODUCTS) + ".",
}
