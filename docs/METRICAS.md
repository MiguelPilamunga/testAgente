# Métricas operativas — OnboardingAgent

Emisión: `src/onboarding/metrics.py` imprime registros **CloudWatch Embedded Metric Format (EMF)** a stdout.
En Lambda, stdout llega a CloudWatch Logs (`/aws/lambda/<stack>-orchestrator`) y CloudWatch extrae las
métricas: sin llamadas a la API `PutMetricData`, sin dependencias y sin latencia adicional.

- **Namespace:** `OnboardingAgent`.
- **Activación:** `METRICS_ENABLED=1|0`. Si no está definido, se activa solo dentro de Lambda
  (`AWS_LAMBDA_FUNCTION_NAME`), así que en local y en los tests queda apagado.
- **Punto único de emisión:** al final de cada ejecución del motor (`Orchestrator._run`, en un `finally`, así
  que también emite si una excepción como `ToolNotPermittedError` corta el flujo) y en cada `resolve`. Las
  métricas de tools y LLM se derivan del tramo de auditoría de esa ejecución. Registry y cliente LLM no llevan
  hooks.
- **Sin PII:** las dimensiones son solo valores de catálogo. Un `product` fuera de catálogo se agrupa como
  `unknown`, porque es texto libre del cliente y podría traer datos personales o disparar la cardinalidad.
  `onboarding_id` (UUID) va como propiedad no indexada, útil para correlacionar en Logs Insights. Nunca se
  emiten nombre ni `document_id`; `tests/test_metrics.py` lo verifica.
- **Rollup:** las métricas con dimensiones publican también el agregado sin dimensiones (`[]`), así que las
  alarmas globales no necesitan `SEARCH`. La excepción es `OnboardingDecision`, cuyo total sin `Status` no
  tiene sentido.

## Catálogo

| Métrica | Unidad | Dimensiones | Pregunta de negocio | Alarma propuesta |
|---|---|---|---|---|
| `OnboardingStarted` | Count | `Product` | ¿Cuánta demanda hay por producto? | Informativa (opcional: 0 en 1 h en horario hábil = posible caída aguas arriba) |
| `OnboardingDecision` | Count | `Status`, `Source` (+ `Product`) | ¿Qué proporción se aprueba, condiciona, rechaza o escala? `Source=start` es el resultado automático y `Source=resolve` el resultado tras la intervención del oficial | Tasa de escalamiento > 30 % en 1 h |
| `Escalations` | Count | `Step`, `Severity` | ¿En qué paso se atasca el flujo y con qué severidad? Mide la carga del equipo de Cumplimiento | `Step=risk, Severity=high` ≥ 10 en 1 h (pico de coincidencias OFAC) |
| `EscalationResolved` | Count | `Action` | ¿Cómo resuelven los oficiales (approve/reject/retry)? | Informativa |
| `TimeToResolveSeconds` | Seconds | `Action` | ¿Cumplimos el SLA de 48 h que se comunica al cliente? | p90 > 172800 s (48 h) en 1 día |
| `StepLatencyMs` | Milliseconds | `Step` | ¿Qué paso (o qué servicio externo) degrada la experiencia? | p95 `Step=identity` > 3000 ms en 15 min |
| `EndToEndLatencyMs` | Milliseconds | `Source` | ¿Respondemos dentro del timeout de API Gateway (29 s)? | p95 > 20000 ms en 15 min |
| `ToolCalls` | Count | `Tool` | ¿Cuánto volumen enviamos a cada servicio (Registro Civil, listas, documentación)? | Informativa (base para tasa de error) |
| `ToolErrors` | Count | `Tool` | ¿Qué servicio externo está fallando? | ≥ 5 en 5 min (cualquier tool) |
| `ToolRetries` | Count | `Tool` | ¿Cuántos casos se salvaron gracias al reintento? | Informativa |
| `ToolDenied` | Count | `Agent` | ¿Algún agente intentó usar una tool fuera de su allowlist? Es una señal de seguridad | **≥ 1 en 5 min → crítica** (nunca debería ocurrir) |
| `LLMCalls` | Count | `Provider` (`anthropic`/`openai`/`template`) | ¿Quién redactó cada texto (respuesta al cliente y propuesta interna)? `template` = sin LLM | Informativa |
| `LLMFallbacks` | Count | — | ¿Cuántas veces el texto no vino del proveedor primario (secundario o plantilla)? | > 20 % de `LLMCalls` en 1 h |
| `LLMOutputRejected` | Count | `Reason` (`too_long`, `approval_terms_in_non_approved`, `rejection_terms_in_approved`) | ¿El LLM intenta contradecir la decisión determinista? Es una señal de calidad y seguridad | ≥ 5 en 15 min |
| `LLMBudgetExhausted` | Count | — | ¿El presupuesto de latencia LLM fuerza el paso a plantilla? Indica un proveedor lento | ≥ 1 en 15 min |

Semántica fina:
- `LLMCalls` se cuenta por texto generado (ResponseAgent y MitigationAgent), con el proveedor que produjo el
  texto final. Si la salida del LLM se rechaza, cuenta como `template`.
- `LLMFallbacks` solo cuenta cuando hay proveedores configurados. Con `LLM_PROVIDER=none` la plantilla es el
  modo normal y no cuenta como fallback.
- `LLMBudgetExhausted` es una aproximación: cuenta cuando el LLM no devolvió texto y el gasto de la ventana
  ya alcanzó el presupuesto.
- `ToolRetries` cuenta cada error que fue seguido de un nuevo intento (`attempt < TOOL_MAX_ATTEMPTS`).
- `TimeToResolveSeconds` se mide desde el evento de auditoría `escalated` de esa escalación hasta el `resolve`.

## KPIs de negocio (metric math)

| KPI | Fórmula | Objetivo orientativo |
|---|---|---|
| Tasa de aprobación automática | `(Decision{APPROVED,start} + Decision{APPROVED_WITH_CONDITIONS,start}) / OnboardingStarted` | ≥ 70 % |
| Tasa de escalamiento | `Decision{ESCALATED,start} / OnboardingStarted` | ≤ 20 % (alarma > 30 %) |
| Tasa de rechazo automático | `Decision{REJECTED,start} / OnboardingStarted` | Vigilar tendencia |
| Tiempo a resolución | `TimeToResolveSeconds` p50 / p90 | p90 < 48 h |
| % fallback LLM | `LLMFallbacks / LLMCalls` (rollup) | < 5 % (alarma > 20 %) |
| Disponibilidad de tools | `1 - ToolErrors / ToolCalls` por `Tool` | ≥ 99 % |

## CloudWatch Logs Insights

Log group: `/aws/lambda/onboarding-agent-dev-orchestrator`.

```sql
-- Decisiones automáticas por estado y producto (últimas 24 h)
filter ispresent(OnboardingDecision) and Source = "start" and ispresent(Product)
| stats sum(OnboardingDecision) as total by Status, Product
| sort total desc

-- Distribución horaria de decisiones (tasa de escalamiento = ESCALATED / suma de la hora;
-- el % exacto y su alarma están en metric math, más abajo)
filter ispresent(OnboardingDecision) and Source = "start" and ispresent(Product)
| stats sum(OnboardingDecision) as total by bin(1h), Status
| sort bin(1h) desc

-- Latencia por paso (p50/p95)
filter ispresent(StepLatencyMs) and ispresent(Step)
| stats pct(StepLatencyMs, 50) as p50, pct(StepLatencyMs, 95) as p95, count(*) as n by Step

-- Errores y reintentos por tool
filter ispresent(Tool) and (ispresent(ToolErrors) or ispresent(ToolRetries))
| stats sum(ToolErrors) as errores, sum(ToolRetries) as reintentos by Tool, bin(15m)

-- Intentos de tool fuera de allowlist (seguridad): qué agente y qué onboarding
filter ispresent(ToolDenied)
| fields @timestamp, Agent, onboarding_id
| sort @timestamp desc

-- Calidad LLM: proveedor, fallbacks y rechazos del guardrail
filter ispresent(LLMCalls) or ispresent(LLMFallbacks) or ispresent(LLMOutputRejected)
| stats sum(LLMCalls) as llamadas, sum(LLMFallbacks) as fallbacks, sum(LLMOutputRejected) as rechazos
        by Provider, Reason

-- Tiempo a resolución de escalamientos (horas)
filter ispresent(TimeToResolveSeconds)
| stats pct(TimeToResolveSeconds, 50) / 3600 as p50_h, pct(TimeToResolveSeconds, 90) / 3600 as p90_h by Action

-- Trazar un onboarding concreto (todas sus métricas)
filter onboarding_id = "<uuid>"
| sort @timestamp asc
```

> Nota: en cada registro EMF las métricas aparecen en la raíz. Los filtros `ispresent(Product)` y
> `ispresent(Step)` evitan contar dos veces `OnboardingDecision`, que se emite en dos registros (con y sin
> `Product`).

## Dashboard propuesto (para que arch lo agregue a `infra/template.yaml`)

Recurso `AWS::CloudWatch::Dashboard` con `DashboardName: !Sub ${AWS::StackName}-ops` y `DashboardBody: !Sub |`
con el JSON siguiente. `${AWS::Region}` lo resuelve `!Sub`.

```json
{
  "widgets": [
    {"type": "metric", "x": 0, "y": 0, "width": 8, "height": 6, "properties": {
      "title": "KPIs de decisión automática (%)", "region": "${AWS::Region}", "view": "timeSeries",
      "stat": "Sum", "period": 3600, "yAxis": {"left": {"min": 0, "max": 100}},
      "metrics": [
        ["OnboardingAgent", "OnboardingStarted", {"id": "started", "visible": false}],
        ["OnboardingAgent", "OnboardingDecision", "Source", "start", "Status", "APPROVED", {"id": "ap", "visible": false}],
        ["OnboardingAgent", "OnboardingDecision", "Source", "start", "Status", "APPROVED_WITH_CONDITIONS", {"id": "awc", "visible": false}],
        ["OnboardingAgent", "OnboardingDecision", "Source", "start", "Status", "ESCALATED", {"id": "esc", "visible": false}],
        ["OnboardingAgent", "OnboardingDecision", "Source", "start", "Status", "REJECTED", {"id": "rej", "visible": false}],
        [{"expression": "100 * (ap + awc) / started", "label": "Aprobación automática %", "id": "kpi_ap"}],
        [{"expression": "100 * esc / started", "label": "Escalamiento %", "id": "kpi_esc"}],
        [{"expression": "100 * rej / started", "label": "Rechazo %", "id": "kpi_rej"}]
      ]}},
    {"type": "metric", "x": 8, "y": 0, "width": 8, "height": 6, "properties": {
      "title": "Solicitudes por producto", "region": "${AWS::Region}", "view": "timeSeries", "stacked": true,
      "stat": "Sum", "period": 300,
      "metrics": [
        ["OnboardingAgent", "OnboardingStarted", "Product", "cuenta_ahorros"],
        ["OnboardingAgent", "OnboardingStarted", "Product", "cuenta_corriente"],
        ["OnboardingAgent", "OnboardingStarted", "Product", "tarjeta_credito"],
        ["OnboardingAgent", "OnboardingStarted", "Product", "unknown"]
      ]}},
    {"type": "metric", "x": 16, "y": 0, "width": 8, "height": 6, "properties": {
      "title": "Escalamientos por paso/severidad", "region": "${AWS::Region}", "view": "timeSeries", "stacked": true,
      "stat": "Sum", "period": 300,
      "metrics": [
        ["OnboardingAgent", "Escalations", "Severity", "medium", "Step", "identity"],
        ["OnboardingAgent", "Escalations", "Severity", "high", "Step", "risk"],
        ["OnboardingAgent", "Escalations", "Severity", "high", "Step", "identity"],
        ["OnboardingAgent", "Escalations", "Severity", "medium", "Step", "risk"],
        ["OnboardingAgent", "Escalations", "Severity", "medium", "Step", "documentation"]
      ]}},
    {"type": "metric", "x": 0, "y": 6, "width": 8, "height": 6, "properties": {
      "title": "Latencia por paso p95 (ms)", "region": "${AWS::Region}", "view": "timeSeries",
      "stat": "p95", "period": 300,
      "metrics": [
        ["OnboardingAgent", "StepLatencyMs", "Step", "identity"],
        ["OnboardingAgent", "StepLatencyMs", "Step", "risk"],
        ["OnboardingAgent", "StepLatencyMs", "Step", "documentation"],
        ["OnboardingAgent", "StepLatencyMs", "Step", "decision"],
        ["OnboardingAgent", "StepLatencyMs", "Step", "response"],
        ["OnboardingAgent", "EndToEndLatencyMs", "Source", "start", {"label": "End-to-end (start)"}]
      ],
      "annotations": {"horizontal": [{"label": "Timeout API GW", "value": 29000}]}}},
    {"type": "metric", "x": 8, "y": 6, "width": 8, "height": 6, "properties": {
      "title": "Tools: llamadas, errores, reintentos, denegadas", "region": "${AWS::Region}", "view": "timeSeries",
      "stat": "Sum", "period": 300,
      "metrics": [
        ["OnboardingAgent", "ToolCalls"],
        ["OnboardingAgent", "ToolErrors"],
        ["OnboardingAgent", "ToolRetries"],
        ["OnboardingAgent", "ToolDenied", {"color": "#d62728"}]
      ]}},
    {"type": "metric", "x": 16, "y": 6, "width": 8, "height": 6, "properties": {
      "title": "LLM: proveedor, fallback y guardrail", "region": "${AWS::Region}", "view": "timeSeries",
      "stat": "Sum", "period": 300,
      "metrics": [
        ["OnboardingAgent", "LLMCalls", "Provider", "anthropic"],
        ["OnboardingAgent", "LLMCalls", "Provider", "openai"],
        ["OnboardingAgent", "LLMCalls", "Provider", "template"],
        ["OnboardingAgent", "LLMFallbacks"],
        ["OnboardingAgent", "LLMOutputRejected"],
        ["OnboardingAgent", "LLMBudgetExhausted"]
      ]}},
    {"type": "metric", "x": 0, "y": 12, "width": 12, "height": 6, "properties": {
      "title": "Tiempo a resolución p50/p90 (h)", "region": "${AWS::Region}", "view": "timeSeries", "period": 3600,
      "metrics": [
        ["OnboardingAgent", "TimeToResolveSeconds", {"id": "p50", "stat": "p50", "visible": false}],
        ["OnboardingAgent", "TimeToResolveSeconds", {"id": "p90", "stat": "p90", "visible": false}],
        [{"expression": "p50 / 3600", "label": "p50 (h)"}],
        [{"expression": "p90 / 3600", "label": "p90 (h)"}]
      ],
      "annotations": {"horizontal": [{"label": "SLA 48 h", "value": 48}]}}},
    {"type": "metric", "x": 12, "y": 12, "width": 12, "height": 6, "properties": {
      "title": "Resoluciones de oficiales", "region": "${AWS::Region}", "view": "bar", "stat": "Sum", "period": 86400,
      "metrics": [
        ["OnboardingAgent", "EscalationResolved", "Action", "approve"],
        ["OnboardingAgent", "EscalationResolved", "Action", "reject"],
        ["OnboardingAgent", "EscalationResolved", "Action", "retry"]
      ]}}
  ]
}
```

## Alarmas propuestas (SAM/CloudFormation)

Todas con `Namespace: OnboardingAgent` y `TreatMissingData: notBreaching`. `AlarmActions` debe apuntar al
tópico SNS o canal de on-call que arch defina.

```yaml
  AlarmToolDenied:            # seguridad: violación de allowlist
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-tool-denied
      AlarmDescription: Un agente intentó usar una tool fuera de su allowlist (crítica)
      Namespace: OnboardingAgent
      MetricName: ToolDenied
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 1
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching

  AlarmToolErrors:            # servicio externo caído
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-tool-errors
      Namespace: OnboardingAgent
      MetricName: ToolErrors
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 5
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching

  AlarmLLMOutputRejected:     # el LLM intenta contradecir la decisión
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-llm-output-rejected
      Namespace: OnboardingAgent
      MetricName: LLMOutputRejected
      Statistic: Sum
      Period: 900
      EvaluationPeriods: 1
      Threshold: 5
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching

  AlarmLLMBudgetExhausted:    # proveedor LLM lento
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-llm-budget-exhausted
      Namespace: OnboardingAgent
      MetricName: LLMBudgetExhausted
      Statistic: Sum
      Period: 900
      EvaluationPeriods: 1
      Threshold: 1
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching

  AlarmEndToEndLatency:       # cerca del timeout de 29 s
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-e2e-latency-p95
      Namespace: OnboardingAgent
      MetricName: EndToEndLatencyMs
      Dimensions: [{Name: Source, Value: start}]
      ExtendedStatistic: p95
      Period: 900
      EvaluationPeriods: 1
      Threshold: 20000
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching

  AlarmTimeToResolve:         # SLA 48 h comunicado al cliente
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-time-to-resolve-p90
      Namespace: OnboardingAgent
      MetricName: TimeToResolveSeconds
      ExtendedStatistic: p90
      Period: 86400
      EvaluationPeriods: 1
      Threshold: 172800
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching

  AlarmEscalationRate:        # > 30 % de solicitudes escaladas en 1 h (mínimo 10 solicitudes)
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-escalation-rate
      EvaluationPeriods: 1
      Threshold: 30
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      Metrics:
        - Id: started
          ReturnData: false
          MetricStat: {Metric: {Namespace: OnboardingAgent, MetricName: OnboardingStarted}, Period: 3600, Stat: Sum}
        - Id: esc
          ReturnData: false
          MetricStat:
            Metric:
              Namespace: OnboardingAgent
              MetricName: OnboardingDecision
              Dimensions: [{Name: Source, Value: start}, {Name: Status, Value: ESCALATED}]
            Period: 3600
            Stat: Sum
        - Id: rate
          Expression: IF(started >= 10, 100 * esc / started, 0)
          Label: Escalamiento %

  AlarmLLMFallbackRate:       # > 20 % de textos no vienen del proveedor primario
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${AWS::StackName}-llm-fallback-rate
      EvaluationPeriods: 1
      Threshold: 20
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      Metrics:
        - Id: calls
          ReturnData: false
          MetricStat: {Metric: {Namespace: OnboardingAgent, MetricName: LLMCalls}, Period: 3600, Stat: Sum}
        - Id: fb
          ReturnData: false
          MetricStat: {Metric: {Namespace: OnboardingAgent, MetricName: LLMFallbacks}, Period: 3600, Stat: Sum}
        - Id: rate
          Expression: IF(calls >= 10, 100 * fb / calls, 0)
          Label: Fallback LLM %
```

Para activar en AWS no hace falta ningún cambio: dentro de Lambda las métricas se emiten por defecto. Para
apagarlas, define `METRICS_ENABLED: "0"` en `Environment.Variables`.
