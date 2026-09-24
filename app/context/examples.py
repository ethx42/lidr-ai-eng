"""Reference estimations injected into the system prompt (the CAG context).

Typed so every few-shot example matches the output contract exactly. Requirement evidence
quotes each meeting summary verbatim; `tests/unit/test_examples.py` enforces it.
"""

from typing import Literal

from pydantic import BaseModel

from app.schemas.estimation import EstimationBreakdown


class ReferenceEstimation(BaseModel):
    size: Literal["small", "medium", "large"]
    meeting_summary: str
    estimation: EstimationBreakdown


DENTAL_CLINIC = ReferenceEstimation(
    size="small",
    meeting_summary="""\
Owner: We're a small dental clinic and our website is ten years old. We want a new website with our services, the team, and opening hours.
Owner: Patients should be able to request an appointment through a form; we'll call them back to confirm.
Receptionist: The requests should arrive in our clinic email inbox.
Owner: It has to look good on phones. We already have the domain and a logo.
""",
    estimation=EstimationBreakdown.model_validate(
        {
            "project_name": "Dental clinic website",
            "summary": (
                "Replace a ten-year-old clinic website with a mobile-first marketing site "
                "presenting services, team, and opening hours, plus an appointment request "
                "form delivered to the clinic's inbox."
            ),
            "requirements": [
                {
                    "id": "R1",
                    "statement": "Website presenting services, team, and opening hours.",
                    "evidence": "We want a new website with our services, the team, and opening hours.",
                },
                {
                    "id": "R2",
                    "statement": "Appointment request form; staff confirm by phone.",
                    "evidence": "Patients should be able to request an appointment through a form",
                },
                {
                    "id": "R3",
                    "statement": "Form submissions delivered to the clinic email inbox.",
                    "evidence": "The requests should arrive in our clinic email inbox.",
                },
                {
                    "id": "R4",
                    "statement": "Responsive, mobile-friendly design.",
                    "evidence": "It has to look good on phones.",
                },
            ],
            "assumptions": [
                {
                    "id": "A1",
                    "statement": "The clinic provides all texts and photos.",
                    "impact_if_wrong": "Copywriting and photography add roughly 15-25 hours.",
                },
                {
                    "id": "A2",
                    "statement": "No CMS: content changes are rare and made by the developer.",
                    "impact_if_wrong": "A headless CMS adds roughly 20 hours.",
                },
                {
                    "id": "A3",
                    "statement": "Hosting on a managed static host; the clinic controls DNS.",
                    "impact_if_wrong": "Custom server setup adds roughly 6-10 hours.",
                },
            ],
            "open_questions": [
                "Who will update the content after launch, and how often?",
                "Is the site needed in more than one language?",
                "What consent text is required for collecting patient contact data?",
            ],
            "tasks": [
                {
                    "id": "T1",
                    "phase": "discovery",
                    "name": "Kickoff, sitemap, and content inventory",
                    "rationale": "Agree on pages and collect existing material.",
                    "basis": ["R1", "A1"],
                    "optimistic_hours": 2,
                    "likely_hours": 4,
                    "pessimistic_hours": 6,
                },
                {
                    "id": "T2",
                    "phase": "ux_ui",
                    "name": "Mobile-first design for five pages",
                    "rationale": "Home, services, team, hours/contact, and appointment form.",
                    "basis": ["R1", "R4"],
                    "optimistic_hours": 8,
                    "likely_hours": 12,
                    "pessimistic_hours": 20,
                },
                {
                    "id": "T3",
                    "phase": "frontend",
                    "name": "Build responsive pages",
                    "rationale": "Static pages from the approved design.",
                    "basis": ["R1", "R4"],
                    "optimistic_hours": 10,
                    "likely_hours": 16,
                    "pessimistic_hours": 24,
                },
                {
                    "id": "T4",
                    "phase": "backend",
                    "name": "Appointment form with email delivery and spam protection",
                    "rationale": "Form endpoint or form service forwarding to the clinic inbox.",
                    "basis": ["R2", "R3"],
                    "optimistic_hours": 4,
                    "likely_hours": 6,
                    "pessimistic_hours": 10,
                },
                {
                    "id": "T5",
                    "phase": "qa",
                    "name": "Cross-device and form testing",
                    "rationale": "Phones, tablets, desktop browsers; end-to-end form delivery.",
                    "basis": ["R2", "R4"],
                    "optimistic_hours": 3,
                    "likely_hours": 4,
                    "pessimistic_hours": 8,
                },
                {
                    "id": "T6",
                    "phase": "devops",
                    "name": "Hosting, DNS, SSL, and deployment",
                    "rationale": "Point the existing domain to the new host.",
                    "basis": ["A3"],
                    "optimistic_hours": 2,
                    "likely_hours": 4,
                    "pessimistic_hours": 6,
                },
                {
                    "id": "T7",
                    "phase": "project_management",
                    "name": "Coordination and client reviews",
                    "rationale": "Two review rounds and launch coordination.",
                    "basis": ["R1"],
                    "optimistic_hours": 3,
                    "likely_hours": 4,
                    "pessimistic_hours": 6,
                },
            ],
            "team": [
                {"role": "Full-stack developer", "count": 1},
                {"role": "UX/UI designer (part-time)", "count": 1},
            ],
            "risks": [
                {
                    "description": "Content arrives late from the clinic.",
                    "impact": "medium",
                    "mitigation": "Agree on a content deadline at kickoff; use placeholders.",
                },
                {
                    "description": "Patient data in the form falls under health privacy rules.",
                    "impact": "medium",
                    "mitigation": "Collect only contact data; add consent text reviewed by the clinic.",
                },
            ],
            "confidence": "high",
            "confidence_rationale": "Small, well-understood scope with few integrations.",
        }
    ),
)

BAKERY_INVENTORY = ReferenceEstimation(
    size="medium",
    meeting_summary="""\
Gerente: Tenemos seis panaderías y controlamos el inventario en hojas de cálculo. Queremos una herramienta web para que cada encargado registre el stock de su local.
Gerente: Las ventas ya pasan por Square, así que el stock debería descontarse solo con cada venta.
Encargada: Necesito una alerta cuando un ingrediente baje del mínimo.
Gerente: También queremos generar los pedidos a proveedores desde la herramienta y ver un informe semanal de mermas.
Gerente: Los encargados usan tablets en la tienda.
""",
    estimation=EstimationBreakdown.model_validate(
        {
            "project_name": "Inventario Panaderías",
            "summary": (
                "Herramienta web de inventario para seis panaderías que sustituye las hojas de "
                "cálculo, descuenta stock automáticamente con las ventas de Square, alerta de "
                "mínimos, genera pedidos a proveedores e informa de mermas semanales."
            ),
            "requirements": [
                {
                    "id": "R1",
                    "statement": "Registro de stock por local desde una herramienta web.",
                    "evidence": "Queremos una herramienta web para que cada encargado registre el stock de su local.",
                },
                {
                    "id": "R2",
                    "statement": "Descuento automático de stock con cada venta de Square.",
                    "evidence": "el stock debería descontarse solo con cada venta",
                },
                {
                    "id": "R3",
                    "statement": "Alerta cuando un ingrediente baja del mínimo.",
                    "evidence": "Necesito una alerta cuando un ingrediente baje del mínimo.",
                },
                {
                    "id": "R4",
                    "statement": "Generación de pedidos a proveedores.",
                    "evidence": "generar los pedidos a proveedores desde la herramienta",
                },
                {
                    "id": "R5",
                    "statement": "Informe semanal de mermas.",
                    "evidence": "ver un informe semanal de mermas",
                },
                {
                    "id": "R6",
                    "statement": "Interfaz optimizada para tablets.",
                    "evidence": "Los encargados usan tablets en la tienda.",
                },
            ],
            "assumptions": [
                {
                    "id": "A1",
                    "statement": (
                        "Existen recetas con cantidades por producto para convertir ventas en "
                        "consumo de ingredientes."
                    ),
                    "impact_if_wrong": "Hace falta un módulo de recetas: +40-60 horas.",
                },
                {
                    "id": "A2",
                    "statement": "Los pedidos se envían por email en PDF, sin integrar sistemas de proveedores.",
                    "impact_if_wrong": "Cada integración con un proveedor suma 20-40 horas.",
                },
                {
                    "id": "A3",
                    "statement": "Solo hay dos roles: encargado de local y gerente.",
                    "impact_if_wrong": "Permisos más finos suman 10-20 horas.",
                },
                {
                    "id": "A4",
                    "statement": "Una única cuenta de Square con acceso a su API y webhooks.",
                    "impact_if_wrong": "Varias cuentas o sin API: +20 horas o cambio de enfoque.",
                },
            ],
            "open_questions": [
                "¿Tenéis recetas con cantidades de ingredientes por producto?",
                "¿Cómo se envían hoy los pedidos a los proveedores?",
                "¿Hay que migrar el histórico de las hojas de cálculo?",
                "¿Cuántos usuarios usarán la herramienta?",
            ],
            "tasks": [
                {
                    "id": "T1",
                    "phase": "discovery",
                    "name": "Análisis de procesos, recetas y API de Square",
                    "rationale": "Validar el flujo de inventario y el acceso a los datos de venta.",
                    "basis": ["R1", "R2", "A1"],
                    "optimistic_hours": 8,
                    "likely_hours": 12,
                    "pessimistic_hours": 20,
                },
                {
                    "id": "T2",
                    "phase": "ux_ui",
                    "name": "Diseño de pantallas para tablet",
                    "rationale": "Stock, alertas, pedidos e informes; uso táctil en tienda.",
                    "basis": ["R1", "R6"],
                    "optimistic_hours": 16,
                    "likely_hours": 24,
                    "pessimistic_hours": 36,
                },
                {
                    "id": "T3",
                    "phase": "backend",
                    "name": "Modelo de datos y API de inventario multi-local",
                    "rationale": "Ingredientes, stock por local, movimientos y mínimos.",
                    "basis": ["R1"],
                    "optimistic_hours": 24,
                    "likely_hours": 36,
                    "pessimistic_hours": 56,
                },
                {
                    "id": "T4",
                    "phase": "backend",
                    "name": "Autenticación y roles",
                    "rationale": "Encargado limitado a su local; gerente ve todos.",
                    "basis": ["A3"],
                    "optimistic_hours": 8,
                    "likely_hours": 12,
                    "pessimistic_hours": 18,
                },
                {
                    "id": "T5",
                    "phase": "integrations",
                    "name": "Webhooks de ventas de Square y descuento por receta",
                    "rationale": "Idempotencia, reintentos y conversión venta → ingredientes.",
                    "basis": ["R2", "A1", "A4"],
                    "optimistic_hours": 24,
                    "likely_hours": 40,
                    "pessimistic_hours": 70,
                },
                {
                    "id": "T6",
                    "phase": "backend",
                    "name": "Alertas de stock mínimo por email",
                    "rationale": "Evaluación tras cada movimiento y resumen diario.",
                    "basis": ["R3"],
                    "optimistic_hours": 8,
                    "likely_hours": 12,
                    "pessimistic_hours": 20,
                },
                {
                    "id": "T7",
                    "phase": "backend",
                    "name": "Pedidos a proveedores en PDF por email",
                    "rationale": "Propuesta de cantidades según mínimos y envío.",
                    "basis": ["R4", "A2"],
                    "optimistic_hours": 16,
                    "likely_hours": 24,
                    "pessimistic_hours": 40,
                },
                {
                    "id": "T8",
                    "phase": "frontend",
                    "name": "Panel web para tablets",
                    "rationale": "Registro de stock, alertas, pedidos e informes.",
                    "basis": ["R1", "R3", "R4", "R6"],
                    "optimistic_hours": 40,
                    "likely_hours": 60,
                    "pessimistic_hours": 90,
                },
                {
                    "id": "T9",
                    "phase": "backend",
                    "name": "Informe semanal de mermas",
                    "rationale": "Agregación por local e ingrediente y exportación.",
                    "basis": ["R5"],
                    "optimistic_hours": 12,
                    "likely_hours": 18,
                    "pessimistic_hours": 30,
                },
                {
                    "id": "T10",
                    "phase": "qa",
                    "name": "Pruebas funcionales y de integración con Square",
                    "rationale": "Incluye pruebas en tablets reales y con ventas de prueba.",
                    "basis": ["R1", "R2"],
                    "optimistic_hours": 20,
                    "likely_hours": 30,
                    "pessimistic_hours": 45,
                },
                {
                    "id": "T11",
                    "phase": "devops",
                    "name": "Infraestructura, CI/CD y despliegue",
                    "rationale": "Entornos de pruebas y producción, copias de seguridad.",
                    "basis": ["R1"],
                    "optimistic_hours": 10,
                    "likely_hours": 16,
                    "pessimistic_hours": 24,
                },
                {
                    "id": "T12",
                    "phase": "project_management",
                    "name": "Gestión del proyecto y formación",
                    "rationale": "Seguimiento semanal y formación de encargados.",
                    "basis": ["R1"],
                    "optimistic_hours": 20,
                    "likely_hours": 28,
                    "pessimistic_hours": 40,
                },
            ],
            "team": [
                {"role": "Desarrollador backend", "count": 1},
                {"role": "Desarrollador frontend", "count": 1},
                {"role": "Diseñador UX/UI (parcial)", "count": 1},
            ],
            "risks": [
                {
                    "description": "No existen recetas con cantidades por producto.",
                    "impact": "high",
                    "mitigation": "Confirmarlo en discovery; planificar el módulo de recetas.",
                },
                {
                    "description": "Limitaciones o retrasos en los webhooks de Square.",
                    "impact": "medium",
                    "mitigation": "Conciliación nocturna contra la API de ventas.",
                },
                {
                    "description": "Baja adopción por parte de los encargados.",
                    "impact": "medium",
                    "mitigation": "Piloto en un local antes de extender a los seis.",
                },
            ],
            "confidence": "medium",
            "confidence_rationale": (
                "El alcance está claro, pero el descuento automático depende de recetas y de la "
                "API de Square, aún sin confirmar."
            ),
        }
    ),
)

FREIGHT_MARKETPLACE = ReferenceEstimation(
    size="large",
    meeting_summary="""\
CEO: We want to build a marketplace where shippers post freight loads and carriers bid on them.
CTO: Carriers' drivers need a mobile app, iOS and Android, that shares live GPS location during a delivery.
CEO: Shippers should see the truck on a map and get an ETA.
CFO: Payments go through the platform: the shipper pays upfront, we hold the money and release it to the carrier after proof of delivery.
Ops: Proof of delivery is a photo and a signature captured in the driver app.
CTO: Our two biggest shippers want loads created automatically from their SAP system.
CEO: We also need an admin backoffice to verify carriers' documents and resolve disputes.
CEO: Launch in Spain and Portugal, so Spanish and Portuguese from day one.
""",
    estimation=EstimationBreakdown.model_validate(
        {
            "project_name": "Freight marketplace",
            "summary": (
                "Two-sided freight marketplace where shippers post loads and carriers bid, with a "
                "driver mobile app for live tracking and proof of delivery, escrow-style payments, "
                "SAP load import for key shippers, and an admin backoffice. Launch in Spain and "
                "Portugal."
            ),
            "requirements": [
                {
                    "id": "R1",
                    "statement": "Shippers post freight loads; carriers bid on them.",
                    "evidence": "a marketplace where shippers post freight loads and carriers bid on them",
                },
                {
                    "id": "R2",
                    "statement": "iOS and Android driver app sharing live GPS during deliveries.",
                    "evidence": "a mobile app, iOS and Android, that shares live GPS location during a delivery",
                },
                {
                    "id": "R3",
                    "statement": "Shippers track the truck on a map with an ETA.",
                    "evidence": "Shippers should see the truck on a map and get an ETA.",
                },
                {
                    "id": "R4",
                    "statement": "Upfront payment held by the platform, released after delivery.",
                    "evidence": "the shipper pays upfront, we hold the money and release it to the carrier after proof of delivery",
                },
                {
                    "id": "R5",
                    "statement": "Proof of delivery with photo and signature in the driver app.",
                    "evidence": "Proof of delivery is a photo and a signature captured in the driver app.",
                },
                {
                    "id": "R6",
                    "statement": "Automatic load creation from two shippers' SAP systems.",
                    "evidence": "want loads created automatically from their SAP system",
                },
                {
                    "id": "R7",
                    "statement": "Admin backoffice for carrier document checks and disputes.",
                    "evidence": "an admin backoffice to verify carriers' documents and resolve disputes",
                },
                {
                    "id": "R8",
                    "statement": "Spanish and Portuguese at launch.",
                    "evidence": "Spanish and Portuguese from day one",
                },
            ],
            "assumptions": [
                {
                    "id": "A1",
                    "statement": "One cross-platform codebase (e.g. React Native) for the driver app.",
                    "impact_if_wrong": "Two native apps add roughly 150-250 hours.",
                },
                {
                    "id": "A2",
                    "statement": "Stripe Connect delayed payouts cover the hold-and-release flow in Spain and Portugal.",
                    "impact_if_wrong": "Another payment provider or licensing adds 80+ hours.",
                },
                {
                    "id": "A3",
                    "statement": "Shippers' IT exposes SAP loads through an existing API or file export.",
                    "impact_if_wrong": "Custom SAP development adds 100-200 hours.",
                },
                {
                    "id": "A4",
                    "statement": "ETA comes from a mapping provider API, not custom routing.",
                    "impact_if_wrong": "Custom truck routing adds 80+ hours.",
                },
            ],
            "open_questions": [
                "What are the bidding rules (deadline, reverse auction, auto-accept)?",
                "How does the platform earn money: commission, subscription, or both?",
                "Which carrier documents must be verified, and is manual review enough?",
                "Do drivers need to work offline in areas without coverage?",
            ],
            "tasks": [
                {
                    "id": "T1",
                    "phase": "discovery",
                    "name": "Product discovery and payment/legal review",
                    "rationale": "Bidding rules, commission model, payment flow compliance.",
                    "basis": ["R1", "R4", "A2"],
                    "optimistic_hours": 24,
                    "likely_hours": 40,
                    "pessimistic_hours": 60,
                },
                {
                    "id": "T2",
                    "phase": "ux_ui",
                    "name": "UX/UI for shipper, carrier, driver, and admin flows",
                    "rationale": "Four user types across web and mobile.",
                    "basis": ["R1", "R2", "R3", "R7"],
                    "optimistic_hours": 60,
                    "likely_hours": 80,
                    "pessimistic_hours": 120,
                },
                {
                    "id": "T3",
                    "phase": "backend",
                    "name": "Loads and bidding domain and API",
                    "rationale": "Load lifecycle, bids, awarding, notifications.",
                    "basis": ["R1"],
                    "optimistic_hours": 50,
                    "likely_hours": 70,
                    "pessimistic_hours": 110,
                },
                {
                    "id": "T4",
                    "phase": "backend",
                    "name": "Accounts, organizations, and roles",
                    "rationale": "Shipper and carrier companies, drivers, admins.",
                    "basis": ["R1", "R7"],
                    "optimistic_hours": 24,
                    "likely_hours": 36,
                    "pessimistic_hours": 56,
                },
                {
                    "id": "T5",
                    "phase": "frontend",
                    "name": "Shipper and carrier web app",
                    "rationale": "Post loads, bid, award, track, pay.",
                    "basis": ["R1", "R3"],
                    "optimistic_hours": 60,
                    "likely_hours": 80,
                    "pessimistic_hours": 120,
                },
                {
                    "id": "T6",
                    "phase": "frontend",
                    "name": "Driver mobile app (iOS and Android)",
                    "rationale": "Assigned deliveries, background location, proof of delivery.",
                    "basis": ["R2", "R5", "A1"],
                    "optimistic_hours": 60,
                    "likely_hours": 80,
                    "pessimistic_hours": 130,
                },
                {
                    "id": "T7",
                    "phase": "integrations",
                    "name": "Live GPS tracking and ETA",
                    "rationale": "Location ingestion, map view, mapping provider ETA.",
                    "basis": ["R2", "R3", "A4"],
                    "optimistic_hours": 40,
                    "likely_hours": 60,
                    "pessimistic_hours": 100,
                },
                {
                    "id": "T8",
                    "phase": "integrations",
                    "name": "Stripe Connect hold-and-release payments",
                    "rationale": "Carrier onboarding, upfront charge, payout on delivery, refunds.",
                    "basis": ["R4", "A2"],
                    "optimistic_hours": 40,
                    "likely_hours": 60,
                    "pessimistic_hours": 100,
                },
                {
                    "id": "T9",
                    "phase": "backend",
                    "name": "Proof of delivery storage and release trigger",
                    "rationale": "Photo/signature upload, audit trail, payout release.",
                    "basis": ["R4", "R5"],
                    "optimistic_hours": 16,
                    "likely_hours": 24,
                    "pessimistic_hours": 40,
                },
                {
                    "id": "T10",
                    "phase": "integrations",
                    "name": "SAP load import for two shippers",
                    "rationale": "Mapping, validation, error handling per shipper.",
                    "basis": ["R6", "A3"],
                    "optimistic_hours": 40,
                    "likely_hours": 70,
                    "pessimistic_hours": 140,
                },
                {
                    "id": "T11",
                    "phase": "frontend",
                    "name": "Admin backoffice",
                    "rationale": "Document verification queue and dispute handling.",
                    "basis": ["R7"],
                    "optimistic_hours": 40,
                    "likely_hours": 60,
                    "pessimistic_hours": 90,
                },
                {
                    "id": "T12",
                    "phase": "frontend",
                    "name": "Spanish and Portuguese localization",
                    "rationale": "i18n setup across web and mobile; translations provided.",
                    "basis": ["R8"],
                    "optimistic_hours": 12,
                    "likely_hours": 20,
                    "pessimistic_hours": 32,
                },
                {
                    "id": "T13",
                    "phase": "qa",
                    "name": "Test plan, automation, and device testing",
                    "rationale": "Payments and tracking need end-to-end and field tests.",
                    "basis": ["R1", "R2", "R4"],
                    "optimistic_hours": 60,
                    "likely_hours": 80,
                    "pessimistic_hours": 120,
                },
                {
                    "id": "T14",
                    "phase": "devops",
                    "name": "Cloud infrastructure, CI/CD, app store releases, monitoring",
                    "rationale": "Web, API, and two mobile store pipelines.",
                    "basis": ["R1", "R2"],
                    "optimistic_hours": 30,
                    "likely_hours": 45,
                    "pessimistic_hours": 70,
                },
                {
                    "id": "T15",
                    "phase": "project_management",
                    "name": "Project management and stakeholder coordination",
                    "rationale": "Multiple stakeholders, two SAP shippers, payment provider.",
                    "basis": ["R1", "R6"],
                    "optimistic_hours": 60,
                    "likely_hours": 80,
                    "pessimistic_hours": 110,
                },
            ],
            "team": [
                {"role": "Backend developer", "count": 2},
                {"role": "Frontend developer", "count": 1},
                {"role": "Mobile developer", "count": 1},
                {"role": "UX/UI designer", "count": 1},
                {"role": "QA engineer", "count": 1},
                {"role": "Project manager", "count": 1},
            ],
            "risks": [
                {
                    "description": "Holding customer funds may require payment licensing.",
                    "impact": "high",
                    "mitigation": "Legal review in discovery; rely on the provider's licensed flow.",
                },
                {
                    "description": "SAP integration depends on shippers' IT availability.",
                    "impact": "high",
                    "mitigation": "Agree on the interface and a contact per shipper at kickoff.",
                },
                {
                    "description": "Background location limits and battery use on mobile OSes.",
                    "impact": "medium",
                    "mitigation": "Prototype tracking on real devices early.",
                },
            ],
            "confidence": "medium",
            "confidence_rationale": (
                "Core flows are clear, but payments, SAP access, and bidding rules are "
                "unconfirmed and carry wide ranges."
            ),
        }
    ),
)

REFERENCE_ESTIMATIONS: list[ReferenceEstimation] = [
    DENTAL_CLINIC,
    BAKERY_INVENTORY,
    FREIGHT_MARKETPLACE,
]
