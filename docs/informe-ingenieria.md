Informe de Ingeniería de Software: Plataforma SaaS Glowlab
1. Resumen Ejecutivo
Este documento técnico detalla la arquitectura y el plan de desarrollo para la plataforma SaaS Glowlab, una solución multi-tenant diseñada para modernizar y escalar la gestión de negocios de servicios, comenzando con salones de belleza. El objetivo es transformar un concepto de automatización inicial (basado en n8n) en un producto de software comercialmente viable, robusto y altamente escalable, utilizando un stack tecnológico moderno y principios de ingeniería de software avanzados. El informe aborda desde la arquitectura de alto nivel hasta el diseño detallado de la base de datos, contratos de API, estrategias de integración (IA, WhatsApp, OCR), seguridad, escalabilidad y un roadmap de desarrollo pragmático.

2. Introducción y Visión Estratégica
La visión estratégica detrás de la plataforma Glowlab es crear un sistema inteligente que no solo optimice la gestión operativa de los negocios de servicios (citas, pagos, horarios), sino que también actúe como un asistente proactivo para el personal y una potente herramienta de marketing. La transición de una solución basada en n8n a un backend propio y modular es una decisión estratégica fundamental para asegurar la escalabilidad, personalización, seguridad y la capacidad multi-tenant necesarias para un producto SaaS.

Este informe sirve como una guía exhaustiva para el equipo de ingeniería, delineando la hoja de ruta técnica para construir una plataforma que pueda adaptarse a diversos verticales de servicios, ofreciendo una experiencia de usuario superior y una eficiencia operativa sin precedentes.

3. Principios de Diseño y Filosofía de Arquitectura
La arquitectura de Glowlab se fundamenta en los siguientes principios clave, inspirados en la Clean Architecture y las mejores prácticas de diseño de sistemas distribuidos:

•	Separación de Responsabilidades (SoC): Cada componente o módulo debe tener una única responsabilidad bien definida, minimizando el acoplamiento y maximizando la cohesión.
•	Modularidad y Desacoplamiento: El sistema se dividirá en módulos lógicos y físicamente independientes, que se comunican a través de interfaces bien definidas (APIs, eventos). Esto facilita el desarrollo paralelo, la mantenibilidad y la escalabilidad independiente.
•	Dominio como Centro: La lógica de negocio (entidades y casos de uso) es el corazón de la aplicación, independiente de frameworks, bases de datos o interfaces de usuario.
•	Escalabilidad Horizontal: El diseño debe permitir escalar el sistema añadiendo más instancias de servicios sin modificar la arquitectura fundamental.
•	Resiliencia y Tolerancia a Fallos: Los componentes deben ser capaces de manejar fallos de forma elegante, con mecanismos de reintento, circuit breakers y degradación de servicio.
•	Seguridad por Diseño: Las consideraciones de seguridad se integran en cada etapa del ciclo de vida del desarrollo, desde el diseño hasta el despliegue.
•	Observabilidad: El sistema debe ser fácilmente monitoreable, con logs, métricas y trazas distribuidas para facilitar la depuración y el diagnóstico.
•	Multi-tenancy N nativo: La arquitectura debe soportar múltiples inquilinos (empresas) desde el primer día, con aislamiento de datos y configuración a nivel de código y base de datos.

4. Arquitectura General del Sistema (Detallada)
La plataforma Glowlab adoptará una arquitectura de microservicios (o servicios bien definidos dentro de un monolito modular) desplegados en contenedores. Un API Gateway actuará como punto de entrada unificado, gestionando la autenticación, autorización y enrutamiento. La comunicación interna se realizará a través de APIs REST síncronas y un sistema de mensajería asíncrono para tareas de fondo.

graph TD
    subgraph Frontend & Clientes
        A[Web Admin Panel (React/Next.js)]
        B[Mobile App (React Native/Expo)]
        C[Chatbot Cliente (WhatsApp)]
        D[Chatbot Trabajadora (WhatsApp)]
    end
 
    subgraph Edge Layer
        E(API Gateway / Load Balancer)
        E -- HTTPS --> F[Auth Service (JWT)]
    end
 
    subgraph Backend Services (FastAPI)
        direction LR
        F -- JWT Validation --> G[Users Service]
        G -- RBAC --> H[Tenants Service]
        H -- Multi-tenant Context --> I[Branches Service]
        I -- Worker Management --> J[Workers Service]
        J -- Availability --> K[Calendar Service]
        K -- Scheduling Logic --> L[Appointments Service]
        L -- Client Interaction --> M[Clients Service]
        M -- Service Catalog --> N[Services Service]
        N -- Payment Processing --> O[Payments Service]
        O -- Voucher Validation --> P[OCR Service]
        P -- AI Interpretation --> Q[AI Service]
        Q -- WhatsApp Communication --> R[WhatsApp Service]
        R -- Notifications --> S[Notifications Service]
        S -- Scheduled Tasks --> T[Scheduler Service]
        T -- Marketing Campaigns --> U[Marketing Service]
        U -- Reporting --> V[Reports Service]
        V -- Analytics --> W[Analytics Service]
    end
 
    subgraph Data Layer
        X[PostgreSQL Database] -- Persistent Storage --> Y(Object Storage / S3)
        Z[Redis Cache / Message Broker] -- Fast Access / Async Tasks --> Backend Services
    end
 
    subgraph Infrastructure & DevOps
        AA[Docker Containers]
        BB[Docker Compose / Coolify]
        CC[VPS Hetzner]
        DD[CI/CD Pipeline (GitHub Actions)]
        EE[Monitoring & Logging (Prometheus/Grafana/ELK)]
    end
 
    A --> E
    B --> E
    C --> R
    D --> R
    E --> G
    E --> H
    E --> I
    E --> J
    E --> K
    E --> L
    E --> M
    E --> N
    E --> O
    E --> P
    E --> Q
    E --> R
    E --> S
    E --> T
    E --> U
    E --> V
    E --> W
 
    G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W --> X
    G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W --> Z
    P --> External_OCR[External OCR API]
    Q --> External_AI[External AI API (OpenAI/Claude/Gemini)]
    R --> External_WhatsApp[Evolution API]
 
    X -- Backups --> Y
    AA --> BB
    BB --> CC
    DD --> AA
    EE --> AA
    EE --> X
    EE --> Z
 
    style A fill:#f9f,stroke:#333,stroke-width:2px
    style B fill:#f9f,stroke:#333,stroke-width:2px
    style C fill:#f9f,stroke:#333,stroke-width:2px
    style D fill:#f9f,stroke:#333,stroke-width:2px
    style E fill:#bbf,stroke:#333,stroke-width:2px
    style F fill:#ccf,stroke:#333,stroke-width:2px
    style G fill:#ccf,stroke:#333,stroke-width:2px
    style H fill:#ccf,stroke:#333,stroke-width:2px
    style I fill:#ccf,stroke:#333,stroke-width:2px
    style J fill:#ccf,stroke:#333,stroke-width:2px
    style K fill:#ccf,stroke:#333,stroke-width:2px
    style L fill:#ccf,stroke:#333,stroke-width:2px
    style M fill:#ccf,stroke:#333,stroke-width:2px
    style N fill:#ccf,stroke:#333,stroke-width:2px
    style O fill:#ccf,stroke:#333,stroke-width:2px
    style P fill:#ccf,stroke:#333,stroke-width:2px
    style Q fill:#ccf,stroke:#333,stroke-width:2px
    style R fill:#ccf,stroke:#333,stroke-width:2px
    style S fill:#ccf,stroke:#333,stroke-width:2px
    style T fill:#ccf,stroke:#333,stroke-width:2px
    style U fill:#ccf,stroke:#333,stroke-width:2px
    style V fill:#ccf,stroke:#333,stroke-width:2px
    style W fill:#ccf,stroke:#333,stroke-width:2px
    style X fill:#ffc,stroke:#333,stroke-width:2px
    style Y fill:#afa,stroke:#333,stroke-width:2px
    style Z fill:#ccf,stroke:#333,stroke-width:2px
    style AA fill:#afa,stroke:#333,stroke-width:2px
    style BB fill:#afa,stroke:#333,stroke-width:2px
    style CC fill:#afa,stroke:#333,stroke-width:2px
    style DD fill:#afa,stroke:#333,stroke-width:2px
    style EE fill:#afa,stroke:#333,stroke-width:2px
    style External_OCR fill:#fcf,stroke:#333,stroke-width:2px
    style External_AI fill:#fcf,stroke:#333,stroke-width:2px
    style External_WhatsApp fill:#fcf,stroke:#333,stroke-width:2px

Componentes Clave y su Interacción:

•	Frontend (Web/Mobile/Chatbots): Las interfaces de usuario (panel de administración web, aplicación móvil para clientes/trabajadoras, y los chatbots de WhatsApp) interactúan con el sistema a través del API Gateway.
•	API Gateway / Load Balancer: Actúa como el punto de entrada unificado. Es responsable de:
◦	Terminación SSL/TLS: Maneja el cifrado y descifrado de las comunicaciones.
◦	Autenticación y Autorización: Valida los JWTs y aplica políticas de autorización básicas antes de reenviar la solicitud.
◦	Rate Limiting: Protege el backend de sobrecargas y ataques de fuerza bruta.
◦	Enrutamiento: Dirige las solicitudes a los servicios de backend apropiados.
•	Servicios de Backend (FastAPI): Cada servicio es un módulo lógico y, potencialmente, un microservicio físico. Encapsulan la lógica de negocio específica y se comunican entre sí a través de APIs REST internas o mediante el Message Broker (Redis).
◦	Auth Service: Gestiona el registro, login, refresco de tokens y la validación de JWTs.
◦	Tenants Service: Administra la información de las empresas (inquilinos) y su configuración.
◦	Users Service: Gestiona los usuarios con acceso al panel administrativo de cada empresa.
◦	Workers Service: Maneja la información de las trabajadoras, sus especialidades y su relación con las sucursales.
◦	Clients Service: Almacena y gestiona la base de datos de clientes finales por cada empresa.
◦	Services Service: Mantiene el catálogo de servicios ofrecidos por cada empresa.
◦	Calendar Service: Gestiona la disponibilidad de las trabajadoras, integrándose con calendarios externos (ej. Google Calendar) y el sistema de horarios interno.
◦	Appointments Service: Orquesta el ciclo de vida de las citas, desde la creación hasta la confirmación y cancelación, interactuando con Calendar, Clients y Notifications Services.
◦	Payments Service: Procesa los pagos, gestiona los adelantos y se integra con el OCR Service para la validación de vouchers.
◦	OCR Service: Un microservicio dedicado que interactúa con APIs externas de OCR para extraer datos estructurados de imágenes (ej. vouchers de pago).
◦	AI Service: Un microservicio que abstrae la interacción con modelos de lenguaje natural (LLMs). Recibe texto libre y devuelve intenciones y entidades estructuradas, sin tomar decisiones de negocio.
◦	WhatsApp Service: Gestiona la comunicación bidireccional con la Evolution API de WhatsApp, manejando webhooks para mensajes entrantes y enviando mensajes salientes.
◦	Notifications Service: Centraliza el envío de notificaciones a través de diversos canales (WhatsApp, email, SMS), utilizando el Message Broker para tareas asíncronas.
◦	Scheduler Service: Un componente interno que orquesta tareas programadas y recurrentes (recordatorios, campañas, solicitudes de horarios), utilizando el Message Broker para la ejecución asíncrona.
◦	Marketing Service: Implementa la lógica para campañas de marketing segmentadas y seguimiento de clientes.
◦	Reports Service: Genera informes analíticos y operativos a partir de los datos de la base de datos.
◦	Analytics Service: Recopila y procesa datos para ofrecer insights sobre el rendimiento del negocio y el comportamiento del cliente.
•	Data Layer:
◦	PostgreSQL Database: La base de datos relacional principal, diseñada para multi-tenancy con aislamiento a nivel de fila. Almacena todos los datos transaccionales y maestros.
◦	Redis Cache / Message Broker: Utilizado como caché distribuida para datos frecuentemente accedidos (ej. sesiones de usuario, configuración de tenant) y como broker de mensajes para colas de tareas asíncronas (ej. Celery, RQ) y eventos entre servicios.
◦	Object Storage (S3-compatible): Para almacenar archivos binarios como imágenes de vouchers, perfiles de usuario, etc.
•	Infraestructura & DevOps:
◦	Docker: Contenerización de todos los servicios para asegurar la portabilidad y consistencia del entorno.
◦	Docker Compose / Coolify: Herramientas para la orquestación de contenedores en un único host (Docker Compose) o para un despliegue simplificado en un VPS (Coolify).
◦	VPS Hetzner: Proveedor de infraestructura subyacente.
◦	CI/CD Pipeline (GitHub Actions): Automatización de pruebas, construcción de imágenes Docker y despliegue continuo.
◦	Monitoring & Logging: Herramientas como Prometheus/Grafana para métricas y ELK Stack (Elasticsearch, Logstash, Kibana) para logs centralizados, esenciales para la observabilidad del sistema.

5. Stack Tecnológico Detallado y Justificación Técnica
La selección de tecnologías se ha realizado con un enfoque en la robustez, rendimiento, escalabilidad, madurez del ecosistema y la capacidad de desarrollo rápido para un producto SaaS de misión crítica.

Categoría	Tecnología	Justificación Técnica Detallada
Backend Framework	FastAPI (Python)	Elegido por su alto rendimiento (comparable a Node.js y Go en benchmarks), gracias a Starlette y Pydantic. Ofrece validación de datos automática y serialización/deserialización con Pydantic, reduciendo errores y acelerando el desarrollo. La documentación OpenAPI (Swagger UI/ReDoc) generada automáticamente es invaluable para la colaboración y el consumo de la API. Su soporte nativo para async/await es crucial para construir APIs I/O-bound eficientes, manejando múltiples conexiones concurrentes sin bloquear el hilo principal. La comunidad activa y la riqueza del ecosistema Python para IA/ML son ventajas adicionales.
Base de Datos Principal	PostgreSQL	Un sistema de gestión de bases de datos relacionales (RDBMS) altamente extensible, robusto y conforme a ACID. Sus características avanzadas como JSONB (para datos semi-estructurados), índices parciales, índices GIN/GiST, y particionamiento de tablas son fundamentales para la escalabilidad y el rendimiento en un entorno multi-tenant. Ofrece una fuerte integridad de datos, soporte para transacciones complejas y una gran comunidad. Es la elección estándar para aplicaciones empresariales que requieren fiabilidad y flexibilidad.
ORM	SQLAlchemy	El ORM más potente y flexible en Python. Permite un mapeo objeto-relacional declarativo y expresivo, pero también ofrece la capacidad de escribir SQL puro cuando se requiere optimización de rendimiento o consultas complejas. Su Core permite construir consultas SQL de forma programática, ofreciendo un control granular. Es esencial para implementar patrones de repositorio y unidad de trabajo en una Clean Architecture, desacoplando la lógica de negocio de los detalles de la base de datos.
Migraciones DB	Alembic	Herramienta de migraciones de base de datos diseñada específicamente para SQLAlchemy. Permite gestionar los cambios en el esquema de la base de datos de forma incremental y reversible, lo cual es crítico para el desarrollo continuo y el despliegue en producción. Soporta migraciones automáticas (autogenerate) y manuales, ofreciendo flexibilidad y control sobre la evolución del esquema.
Autenticación	JWT (JSON Web Tokens)	Un estándar abierto (RFC 7519) para la creación de tokens de acceso que afirman la identidad de un usuario. Los JWTs son autocontenidos y stateless, lo que los hace ideales para APIs RESTful y arquitecturas distribuidas, ya que el servidor no necesita mantener el estado de la sesión. Esto mejora la escalabilidad horizontal. Se utilizarán tokens de acceso de corta duración y tokens de refresco para una mayor seguridad.
Cache y Colas	Redis	Un almacén de datos en memoria de código abierto que funciona como base de datos, caché y broker de mensajes. Su velocidad excepcional lo hace ideal para caching de datos frecuentes (reduciendo la carga de la DB), gestión de sesiones, y como backend para colas de tareas asíncronas (ej. Celery o RQ). Soporta estructuras de datos complejas (listas, hashes, sets) y operaciones atómicas, crucial para la concurrencia y la resiliencia.
Mensajería (WhatsApp)	Evolution API	Una API de WhatsApp que proporciona una interfaz programática para la comunicación bidireccional. Es fundamental para la interacción conversacional con clientes y trabajadoras, permitiendo el envío y recepción de mensajes, gestión de plantillas y webhooks para eventos en tiempo real. Su elección se basa en la capacidad de manejar un alto volumen de mensajes y la integración con el ecosistema de WhatsApp Business.
Inteligencia Artificial	API de OpenAI (GPT-4o o similar)	Proporciona acceso a modelos de lenguaje grandes (LLMs) de última generación. Se utilizará para la interpretación de lenguaje natural, extrayendo intenciones y entidades de mensajes de texto libre. La arquitectura incluirá una capa de abstracción (ej. un patrón Strategy o Adapter) para permitir un cambio transparente a otros proveedores de LLM (Claude, Gemini) en el futuro, mitigando el riesgo de dependencia de un único proveedor y facilitando la optimización de costos/rendimiento.
OCR	API especializada (ej. Google Vision API, Tesseract como servicio)	Para la extracción de texto de imágenes, específicamente para la validación de vouchers de pago. Se priorizará una API basada en la nube (ej. Google Vision API) por su alta precisión, escalabilidad y facilidad de integración, aunque se podría considerar una solución auto-hosteada (Tesseract) si las restricciones de costo o privacidad lo requieren. El servicio de OCR encapsulará la lógica de preprocesamiento de imágenes y post-procesamiento del texto extraído.
Frontend	React / Next.js	React para construir interfaces de usuario declarativas y reactivas. Next.js como framework de React que añade capacidades de Server-Side Rendering (SSR) o Static Site Generation (SSG), mejorando el rendimiento inicial, el SEO y la experiencia del usuario. Ofrece enrutamiento basado en archivos, optimización de imágenes y un ecosistema maduro para el desarrollo de aplicaciones web modernas y complejas.
Contenerización	Docker	Estándar de facto para la contenerización de aplicaciones. Asegura la portabilidad (el mismo contenedor funciona en cualquier entorno), aislamiento de dependencias y consistencia entre desarrollo, pruebas y producción. Facilita el despliegue, la escalabilidad y la gestión del ciclo de vida de los servicios.
Orquestación (Local/VPS)	Docker Compose / Coolify	Docker Compose para la definición y ejecución de aplicaciones multi-contenedor en un único host, ideal para entornos de desarrollo y staging. Coolify como una plataforma de código abierto para auto-hostear aplicaciones en un VPS, simplificando la orquestación, el despliegue continuo, la gestión de certificados SSL y la monitorización, ofreciendo una alternativa más ligera a Kubernetes para equipos pequeños/medianos.
Infraestructura Cloud	VPS Hetzner	Proveedor de infraestructura de alto rendimiento y bajo costo, ofreciendo control total sobre el entorno del servidor. Ideal para el despliegue inicial y el crecimiento controlado, permitiendo una migración a proveedores de nube más grandes (AWS, GCP, Azure) si la escala lo justifica en el futuro.
Control de Versiones	Git / GitHub	Git como sistema de control de versiones distribuido para la colaboración, seguimiento de cambios y gestión de ramas. GitHub como plataforma de alojamiento de repositorios, facilitando la revisión de código, CI/CD y gestión de proyectos.
Desarrollo Asistido por IA	Cursor, OpenHands, ChatGPT Agente	Herramientas de IA que se integrarán en el flujo de trabajo de desarrollo para acelerar la codificación (Cursor), automatizar tareas repetitivas y refactorizaciones (OpenHands), y asistir en el diseño arquitectónico y la resolución de problemas complejos (ChatGPT Agente). Esto optimizará la productividad del equipo de ingeniería y permitirá una mayor concentración en la lógica de negocio y la innovación.
6. Arquitectura SaaS Multi-tenant: Estrategias de Aislamiento
La implementación de la capacidad multi-tenant es crítica para el modelo de negocio de Glowlab. Se ha optado por un modelo de Base de Datos Compartida, Esquema Compartido con Aislamiento a Nivel de Fila (Shared Database, Shared Schema, Row-Level Isolation). Esta estrategia ofrece un buen equilibrio entre costo, complejidad de gestión y aislamiento de datos para la fase inicial y de crecimiento del producto.

Jerarquía de Entidades y Propagación del tenant_id:
La clave tenant_id (UUID) será la columna principal para el aislamiento. Se propagará a través de todas las tablas transaccionales y maestras que contengan datos específicos de un inquilino. Las tablas que son globales (ej. users para super-administradores de la plataforma, o tablas de configuración global) no contendrán tenant_id.

1	Tenant (Empresa): Entidad raíz. Cada Tenant tendrá un id (UUID) único.
2	Branch (Sucursal): Relacionada con Tenant (tenant_id). Una empresa puede tener múltiples sucursales.
3	Worker (Trabajadora): Relacionada con Tenant (tenant_id) y Branch (branch_id). Las trabajadoras pertenecen a una empresa y pueden estar asignadas a una o más sucursales.
4	Client (Cliente): Relacionada con Tenant (tenant_id). Los clientes son únicos dentro del contexto de una empresa. Un mismo cliente físico puede ser cliente de diferentes empresas, pero se registrará de forma independiente en cada Tenant.
5	Service (Servicio): Relacionada con Tenant (tenant_id). Catálogo de servicios ofrecidos por cada empresa.
6	Appointment (Cita): Relacionada con Tenant (tenant_id), Branch (branch_id), Client (client_id), Worker (worker_id) y Service (service_id).
7	Payment (Pago): Relacionada con Tenant (tenant_id) y Appointment (appointment_id).
8	Conversation (Conversación): Relacionada con Tenant (tenant_id), Client (client_id) y Worker (worker_id).

Implementación del Aislamiento:
•	Middleware de tenant_id: En el backend de FastAPI, se implementará un middleware que extraiga el tenant_id del token JWT (o de un encabezado HTTP específico) y lo inyecte en el contexto de la solicitud. Todas las operaciones de base de datos subsiguientes utilizarán este tenant_id para filtrar automáticamente los datos.
•	Filtros de Base de Datos: SQLAlchemy se configurará para aplicar automáticamente filtros WHERE tenant_id = current_tenant_id en todas las consultas relevantes. Esto se puede lograr mediante el uso de eventos de SQLAlchemy o un patrón de repositorio que encapsule la lógica de filtrado.
•	Seguridad a Nivel de Fila (RLS) en PostgreSQL: Para una capa adicional de seguridad y para hacer cumplir el aislamiento a nivel de base de datos, se pueden utilizar las políticas de seguridad a nivel de fila de PostgreSQL. Esto asegura que incluso si una consulta accidentalmente omite el filtro tenant_id, la base de datos impedirá el acceso a datos de otros inquilinos.

Consideraciones para el Crecimiento:
Aunque el aislamiento a nivel de fila es adecuado para el inicio, se mantendrá la flexibilidad para migrar a modelos de aislamiento más estrictos (ej. Shared Database, Separate Schema o Separate Database per Tenant) si las necesidades de seguridad, rendimiento o cumplimiento normativo lo exigen en el futuro. La modularidad de la arquitectura facilitará esta transición. 
(Content truncated due to size limit. Use line ranges to read remaining content)

7. Modelo de Datos Detallado (PostgreSQL)
El esquema de base de datos está diseñado para soportar la funcionalidad multi-tenant y las operaciones transaccionales de la plataforma. Se utilizarán tipos de datos optimizados para PostgreSQL y se establecerán relaciones claras entre las entidades.

7.1. Diagrama Entidad-Relación (ERD) Completo
erDiagram
    TENANT { 
        UUID id PK
        VARCHAR name
        VARCHAR subdomain UNIQUE
        VARCHAR api_key_whatsapp
        TIMESTAMP created_at
        TIMESTAMP updated_at
        BOOLEAN is_active
    }
 
    BRANCH { 
        UUID id PK
        UUID tenant_id FK
        VARCHAR name
        VARCHAR address
        VARCHAR timezone
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    USER { 
        UUID id PK
        UUID tenant_id FK
        VARCHAR email UNIQUE
        VARCHAR password_hash
        VARCHAR role ENUM("ADMIN", "OWNER", "STAFF")
        BOOLEAN is_active
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    WORKER { 
        UUID id PK
        UUID tenant_id FK
        UUID branch_id FK
        VARCHAR name
        VARCHAR phone UNIQUE
        JSONB specialties
        VARCHAR calendar_id
        BOOLEAN is_active
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    SERVICE { 
        UUID id PK
        UUID tenant_id FK
        VARCHAR name
        TEXT description
        NUMERIC(10,2) price
        INTEGER duration_minutes
        BOOLEAN is_active
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    CLIENT { 
        UUID id PK
        UUID tenant_id FK
        VARCHAR name
        VARCHAR phone UNIQUE
        TIMESTAMP last_visit
        JSONB preferences_json
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    APPOINTMENT { 
        UUID id PK
        UUID tenant_id FK
        UUID branch_id FK
        UUID client_id FK
        UUID worker_id FK
        UUID service_id FK
        TIMESTAMP start_time
        TIMESTAMP end_time
        VARCHAR status ENUM("PENDING", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")
        NUMERIC(10,2) total_amount
        NUMERIC(10,2) advance_payment
        BOOLEAN advance_paid
        TEXT notes
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    PAYMENT { 
        UUID id PK
        UUID tenant_id FK
        UUID appointment_id FK
        NUMERIC(10,2) amount
        VARCHAR method ENUM("YAPE", "CASH", "CARD", "TRANSFER")
        VARCHAR status ENUM("PENDING", "PAID", "REFUNDED")
        VARCHAR transaction_id UNIQUE
        TEXT voucher_url
        JSONB ocr_data_json
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    CONVERSATION { 
        UUID id PK
        UUID tenant_id FK
        UUID client_id FK
        UUID worker_id FK
        VARCHAR direction ENUM("INBOUND", "OUTBOUND")
        TEXT message_body
        JSONB metadata_json
        TIMESTAMP created_at
    }
 
    SCHEDULE { 
        UUID id PK
        UUID worker_id FK
        INTEGER day_of_week ENUM(0,1,2,3,4,5,6) -- 0=Monday, 6=Sunday
        TIME start_time
        TIME end_time
        BOOLEAN is_available
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    NOTIFICATION { 
        UUID id PK
        UUID tenant_id FK
        UUID recipient_id FK -- Can be client_id or worker_id
        VARCHAR recipient_type ENUM("CLIENT", "WORKER")
        VARCHAR type ENUM("APPOINTMENT_REMINDER", "MARKETING_PROMO", "SCHEDULE_REQUEST", "POST_SERVICE_FOLLOWUP", "REPORT")
        TEXT message_body
        VARCHAR channel ENUM("WHATSAPP", "EMAIL", "SMS")
        VARCHAR status ENUM("PENDING", "SENT", "FAILED", "DELIVERED", "READ")
        TIMESTAMP scheduled_at
        TIMESTAMP sent_at
        JSONB metadata_json
        TIMESTAMP created_at
    }
 
    MARKETING_CAMPAIGN { 
        UUID id PK
        UUID tenant_id FK
        UUID worker_id FK -- Optional, if campaign is worker-specific
        VARCHAR name
        TEXT description
        VARCHAR target_audience_type ENUM("ALL_CLIENTS", "SERVICE_BASED", "LAST_VISIT_BASED", "WORKER_SPECIFIC")
        JSONB target_criteria_json
        TEXT message_template
        TEXT image_url
        TIMESTAMP scheduled_at
        VARCHAR status ENUM("DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
 
    REPORT { 
        UUID id PK
        UUID tenant_id FK
        UUID worker_id FK -- Optional, for individual worker reports
        VARCHAR type ENUM("MONTHLY_SUMMARY", "DAILY_AGENDA")
        DATE report_date
        TEXT report_content_url -- Link to generated report file (PDF/CSV)
        JSONB summary_data_json
        TIMESTAMP created_at
    }
 
    TENANT ||--o{ BRANCH : "has"
    TENANT ||--o{ USER : "manages"
    TENANT ||--o{ WORKER : "employs"
    TENANT ||--o{ SERVICE : "offers"
    TENANT ||--o{ CLIENT : "serves"
    TENANT ||--o{ APPOINTMENT : "orchestrates"
    TENANT ||--o{ PAYMENT : "processes"
    TENANT ||--o{ CONVERSATION : "logs"
    TENANT ||--o{ NOTIFICATION : "sends"
    TENANT ||--o{ MARKETING_CAMPAIGN : "runs"
    TENANT ||--o{ REPORT : "generates"
 
    BRANCH ||--o{ WORKER : "employs at"
    BRANCH ||--o{ APPOINTMENT : "hosts"
 
    WORKER ||--o{ APPOINTMENT : "assigned to"
    WORKER ||--o{ SCHEDULE : "defines"
    WORKER ||--o{ CONVERSATION : "participates in"
 
    CLIENT ||--o{ APPOINTMENT : "books"
    CLIENT ||--o{ CONVERSATION : "participates in"
 
    SERVICE ||--o{ APPOINTMENT : "for"
 
    APPOINTMENT ||--o{ PAYMENT : "has"
    APPOINTMENT ||--o{ CONVERSATION : "related to"
 
    PAYMENT ||--o{ APPOINTMENT : "for"
 
    NOTIFICATION ||--o{ CLIENT : "to"
    NOTIFICATION ||--o{ WORKER : "to"
 
    MARKETING_CAMPAIGN ||--o{ WORKER : "by"
    REPORT ||--o{ WORKER : "for"

7.2. Justificación de Tipos de Datos y Relaciones:
•	UUID para IDs: Proporciona identificadores únicos globalmente, lo que es beneficioso para sistemas distribuidos, evita colisiones en entornos multi-tenant y mejora la seguridad al dificultar la enumeración de recursos. Son ideales para claves primarias (PK) y foráneas (FK).
•	VARCHAR para Textos Cortos: Utilizado para nombres, direcciones, roles, estados, etc., donde la longitud es limitada y conocida.
•	TEXT para Descripciones Largas: Para campos como description o message_body donde el contenido puede ser extenso.
•	NUMERIC(10,2) para Moneda: Asegura precisión en los cálculos financieros, evitando problemas de coma flotante. 10 es la precisión total y 2 son los decimales.
•	TIMESTAMP para Fechas y Horas: Almacena la fecha y hora con zona horaria, crucial para la gestión de citas y horarios en diferentes ubicaciones geográficas. created_at y updated_at son estándares para auditoría.
•	BOOLEAN para Flags: Para estados binarios como is_active, advance_paid.
•	JSONB para Datos Semi-estructurados: Columnas como specialties (lista de especialidades de una trabajadora), preferences_json (preferencias del cliente), ocr_data_json (datos extraídos por OCR) y metadata_json (información adicional de conversaciones o notificaciones) permiten almacenar datos flexibles sin modificar el esquema de la base de datos. PostgreSQL optimiza las consultas sobre JSONB.
•	ENUM para Estados Fijos: Para campos como role, status, method, direction, type donde los valores posibles son un conjunto predefinido. Esto mejora la integridad de los datos y la legibilidad del esquema.
•	UNIQUE Constraints: Aseguran la unicidad de campos como email (para users), phone (para workers y clients dentro de un tenant), subdomain (para tenants) y transaction_id (para payments).
•	Claves Foráneas (FK): Establecen relaciones entre tablas, garantizando la integridad referencial. La mayoría de las tablas transaccionales y maestras incluyen tenant_id como clave foránea para hacer cumplir el aislamiento multi-tenant.

7.3. Consideraciones de Rendimiento y Optimización:
•	Indexación: Se crearán índices en todas las claves primarias y foráneas automáticamente. Adicionalmente, se añadirán índices en columnas frecuentemente consultadas (ej. start_time en appointments, phone en clients y workers, email en users, created_at en conversations y notifications).
•	Particionamiento: Para tablas con un alto volumen de datos históricos (ej. conversations, notifications, reports), se considerará el particionamiento por tenant_id o por fecha para mejorar el rendimiento de las consultas y la gestión de datos.
•	Optimización de Consultas: Se utilizarán herramientas como EXPLAIN ANALYZE en PostgreSQL para identificar y optimizar consultas lentas.

8. Contratos de API y Lógica de Negocio por Módulo
Cada módulo del backend expondrá una API RESTful con contratos bien definidos utilizando Pydantic para la validación de esquemas de entrada y salida. A continuación, se detallan ejemplos de endpoints y la lógica de negocio asociada.

8.1. Módulo Auth
Descripción: Gestiona la autenticación de usuarios (propietarios de empresas, administradores, personal) y la emisión/validación de JWTs.

Endpoints:

•	POST /auth/register
◦	Request Body: {'email': 'str', 'password': 'str', 'tenant_name': 'str', 'branch_name': 'str'}
◦	Response: {'access_token': 'str', 'token_type': 'bearer'}
◦	Lógica: Crea un nuevo Tenant, un User con rol OWNER, una Branch inicial y devuelve un JWT.
•	POST /auth/login
◦	Request Body: {'email': 'str', 'password': 'str'}
◦	Response: {'access_token': 'str', 'token_type': 'bearer'}
◦	Lógica: Valida credenciales, genera un JWT que incluye user_id, tenant_id y role.
•	POST /auth/refresh
◦	Request Body: {'refresh_token': 'str'}
◦	Response: {'access_token': 'str', 'token_type': 'bearer'}
◦	Lógica: Emite un nuevo token de acceso si el token de refresco es válido.

8.2. Módulo Tenants
Descripción: Gestión de la información de las empresas (inquilinos) que utilizan la plataforma.

Endpoints:

•	GET /tenants/{tenant_id}
◦	Response: {'id': 'UUID', 'name': 'str', 'subdomain': 'str', 'is_active': 'bool', ...}
◦	Lógica: Recupera la información del tenant actual (requiere tenant_id del JWT).
•	PUT /tenants/{tenant_id}
◦	Request Body: {'name': 'str', 'subdomain': 'str', 'api_key_whatsapp': 'str'}
◦	Response: {'id': 'UUID', 'name': 'str', ...}
◦	Lógica: Actualiza la configuración del tenant.

8.3. Módulo Workers
Descripción: Gestión de las trabajadoras, sus especialidades y horarios.

Endpoints:

•	POST /tenants/{tenant_id}/workers
◦	Request Body: {'name': 'str', 'phone': 'str', 'branch_id': 'UUID', 'specialties': ['str']}
◦	Response: {'id': 'UUID', 'name': 'str', ...}
◦	Lógica: Crea una nueva trabajadora asociada al tenant y sucursal.
•	GET /tenants/{tenant_id}/workers/{worker_id}/availability
◦	Query Params: start_date: date, end_date: date
◦	Response: [{'date': 'date', 'available_slots': ['time']}]
◦	Lógica: Consulta el Calendar Service para obtener la disponibilidad de una trabajadora en un rango de fechas.

8.4. Módulo Appointments
Descripción: Gestión del ciclo de vida de las citas.

Endpoints:

•	POST /tenants/{tenant_id}/appointments
◦	Request Body: {'client_id': 'UUID', 'worker_id': 'UUID', 'service_id': 'UUID', 'start_time': 'datetime', 'end_time': 'datetime', 'advance_payment': 'numeric'}
◦	Response: {'id': 'UUID', 'status': 'PENDING', ...}
◦	Lógica: Crea una cita en estado PENDING. Si advance_payment > 0, el Payments Service es notificado para iniciar el proceso de pago.
•	PUT /tenants/{tenant_id}/appointments/{appointment_id}/status
◦	Request Body: {'status': 'CONFIRMED' | 'CANCELLED' | 'COMPLETED' | 'NO_SHOW'}
◦	Response: {'id': 'UUID', 'status': 'CONFIRMED', ...}
◦	Lógica: Actualiza el estado de la cita. Dispara notificaciones relevantes (ej. confirmación al cliente, notificación a la trabajadora).

8.5. Módulo Payments
Descripción: Procesamiento y validación de pagos.

Endpoints:

•	POST /tenants/{tenant_id}/payments/process-advance
◦	Request Body: {'appointment_id': 'UUID', 'amount': 'numeric', 'method': 'YAPE'}
◦	Response: {'payment_id': 'UUID', 'status': 'PENDING', 'instructions': 'str'}
◦	Lógica: Genera instrucciones de pago y notifica al cliente. Espera la imagen del voucher.
•	POST /tenants/{tenant_id}/payments/{payment_id}/validate-ocr
◦	Request Body: {'voucher_image_url': 'str'}
◦	Response: {'payment_id': 'UUID', 'status': 'PAID' | 'FAILED', 'details': 'json'}
◦	Lógica: Envía la imagen al OCR Service, valida los datos extraídos y actualiza el estado del pago y la cita asociada.

8.6. Módulo WhatsApp
Descripción: Interfaz con la Evolution API para la comunicación bidireccional.

Endpoints:

•	POST /whatsapp/webhook
◦	Request Body: {'event': 'str', 'data': 'json'} (estructura definida por Evolution API)
◦	Response: {'status': 'success'}
◦	Lógica: Recibe mensajes entrantes. El WhatsApp Service parsea el mensaje, lo registra en Conversations y lo envía al AI Service para interpretación. Luego, la lógica de negocio apropiada es invocada.
•	POST /whatsapp/send-message
◦	Request Body: {'tenant_id': 'UUID', 'recipient_phone': 'str', 'message': 'str', 'template_name': 'str', 'template_params': 'json'}
◦	Response: {'status': 'sent', 'message_id': 'str'}
◦	Lógica: Envía un mensaje de texto o una plantilla de WhatsApp a un número específico.

8.7. Módulo AI
Descripción: Abstracción para la interacción con modelos de lenguaje natural (LLMs).

Endpoints:

•	POST /ai/interpret-message
◦	Request Body: {'tenant_id': 'UUID', 'message_text': 'str', 'context': 'json'}
◦	Response: {'intent': 'str', 'entities': 'json', 'confidence': 'float'}
◦	Lógica: Envía el message_text y el context (ej. historial de conversación, servicios disponibles) al LLM configurado. El LLM devuelve la intención y las entidades estructuradas. Este servicio no toma decisiones de negocio, solo interpreta.

8.8. Módulo OCR
Descripción: Servicio dedicado a la extracción de texto de imágenes.

Endpoints:

•	POST /ocr/process-image
◦	Request Body: {'image_url': 'str', 'document_type': 'str'}
◦	Response: {'extracted_data': 'json', 'confidence': 'float'}
◦	Lógica: Descarga la imagen de image_url, la envía a la API externa de OCR, procesa la respuesta y devuelve los datos estructurados. document_type (ej. 'YAPE_VOUCHER') ayuda a guiar la extracción.

9. Orquestación de la Inteligencia Artificial (IA)
La IA en Glowlab se concibe como un componente de procesamiento de lenguaje natural (NLP), no como un motor de reglas de negocio. Su rol es puramente interpretativo, transformando entradas de lenguaje humano en datos estructurados que la lógica de negocio del backend pueda consumir. Esta separación es crucial para la fiabilidad, auditabilidad y escalabilidad del sistema.

9.1. Flujo de Procesamiento de Mensajes con IA:
graph TD
    A[Cliente/Trabajadora] -- Mensaje WhatsApp --> B(Evolution API)
    B -- Webhook --> C(WhatsApp Service)
    C -- Publica Evento (MessageReceived) --> D(Message Broker / Redis)
 
    subgraph Backend Services
        E[AI Service Listener] -- Consume Evento --> C
        C -- Llama External AI API --> F[OpenAI/Claude/Gemini API]
        F -- JSON Response --> C
        C -- Publica Evento (IntentDetected) --> D
 
        G[Business Logic Listener] -- Consume Evento (IntentDetected) --> C
        C -- Invoca Use Case (e.g., BookAppointmentUseCase) --> H[Appointments Service]
        H -- Interactúa con DB/Otros Servicios --> I[PostgreSQL/Calendar Service]
        I -- Genera Respuesta/Acción --> H
        H -- Publica Evento (ActionCompleted/ResponseReady) --> D
 
        J[WhatsApp Service Listener] -- Consume Evento (ResponseReady) --> C
        C -- Envía Mensaje Saliente --> B
    end

Pasos Detallados:

9	Mensaje Entrante: Un cliente o trabajadora envía un mensaje por WhatsApp.
10	Webhook: La Evolution API envía un webhook al WhatsApp Service del backend.
11	Publicación de Evento: El WhatsApp Service registra el mensaje en la tabla Conversations y publica un evento MessageReceived en el Message Broker (Redis).
12	Interpretación por IA: El AI Service (actuando como un listener) consume el evento MessageReceived. Extrae el texto del mensaje y, opcionalmente, el contexto de la conversación (historial reciente) de la base de datos. Luego, llama a la API externa de IA (ej. OpenAI) con un prompt cuidadosamente diseñado para extraer la intención y las entidades.
◦	Prompt Engineering: El prompt incluirá instrucciones claras sobre el formato de salida JSON esperado, las posibles intenciones (ej. book_appointment, cancel_appointment, ask_schedule) y las entidades relevantes (fecha, hora, servicio, nombre de trabajadora).
◦	Respuesta de IA: La API de IA devuelve un JSON estructurado con la intent, entities y un confidence score.
13	Publicación de Intención: El AI Service publica un evento IntentDetected en el Message Broker, incluyendo el JSON interpretado.
14	Lógica de Negocio: Un listener en el Appointments Service (o el servicio correspondiente a la intención detectada) consume el evento IntentDetected. Este servicio es el responsable de:
◦	Validar y Normalizar: Convertir las entidades (ej. "mañana" a una fecha específica) y validar contra la lógica de negocio (ej. ¿el servicio existe? ¿la trabajadora está disponible?).
◦	Tomar Decisiones: Basado en la intención y las entidades, el servicio decide la acción a tomar (ej. buscar disponibilidad, crear una cita, solicitar más información).
◦	Interactuar con Otros Servicios/DB: Realiza las operaciones necesarias en la base de datos o invoca otros servicios (ej. Calendar Service para verificar disponibilidad).
15	Generación de Respuesta: Una vez que la lógica de negocio ha procesado la solicitud, genera una respuesta (ej. "Ok, tengo disponibilidad para uñas con María mañana a las 3 PM. ¿Confirma?"). Esta respuesta se publica como un evento ResponseReady.
16	Envío de Mensaje Saliente: El WhatsApp Service (actuando como otro listener) consume el evento ResponseReady y utiliza la Evolution API para enviar el mensaje de vuelta al cliente/trabajadora.

9.2. Abstracción de Proveedor de IA:
Para garantizar la flexibilidad y la resiliencia frente a cambios en los proveedores de IA, se implementará un patrón de diseño Strategy o Adapter en el AI Service. Esto permitirá cambiar entre OpenAI, Claude, Gemini u otros LLMs con una configuración mínima, sin afectar la lógica de negocio principal.

# ai_service/llm_provider.py
 
from abc import ABC, abstractmethod
from typing import Dict, Any
 
class LLMProvider(ABC):
    @abstractmethod
    def interpret_message(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        pass
 
class OpenAIProvider(LLMProvider):
    def interpret_message(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        # Lógica para llamar a la API de OpenAI
        # ...
        return {"intent": "book_appointment", "entities": {...}, "confidence": 0.9}
 
class ClaudeProvider(LLMProvider):
    def interpret_message(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        # Lógica para llamar a la API de Claude
        # ...
        return {"intent": "book_appointment", "entities": {...}, "confidence": 0.85}
 
# ai_service/service.py
 
class AIService:
    def __init__(self, provider: LLMProvider):
        self.provider = provider
 
    def process_message(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.provider.interpret_message(message, context)
 
# Uso en el backend
# from ai_service.llm_provider import OpenAIProvider
# from ai_service.service import AIService
# ai_provider = OpenAIProvider()
# ai_service = AIService(ai_provider)
# result = ai_service.process_message("Quiero una cita...", {...})

10. Scheduler Interno y Procesamiento Asíncrono
El Scheduler Service reemplaza la funcionalidad de n8n para tareas programadas y asíncronas, siendo un componente crítico para la automatización proactiva. Se construirá utilizando Celery (o un framework similar como RQ) con Redis como broker de mensajes y backend de resultados.

10.1. Arquitectura del Scheduler:
graph TD
    A[Backend Services (FastAPI)] -- Dispara Tarea Asíncrona --> B(Celery Producer)
    B -- Envía Mensaje --> C(Redis Message Broker)
 
    subgraph Celery Workers
        D[Celery Worker 1] -- Consume Mensaje --> C
        E[Celery Worker 2] -- Consume Mensaje --> C
        F[Celery Beat (Scheduler)] -- Tareas Programadas --> B
    end
 
    D -- Ejecuta Tarea --> G[Lógica de Negocio (e.g., Notifications Service, Marketing Service)]
    E -- Ejecuta Tarea --> G
    G -- Interactúa con DB/APIs Externas --> H[PostgreSQL/Evolution API/OpenAI API]
    G -- Almacena Resultados --> I[Redis Result Backend]

Componentes:

•	Celery Producer: Cualquier parte del backend de FastAPI que necesite ejecutar una tarea en segundo plano o programada. En lugar de ejecutar la lógica directamente, envía un mensaje a Celery.
•	Redis Message Broker: Actúa como una cola de mensajes donde los productores envían tareas y los workers las recogen. Redis es ideal por su velocidad y fiabilidad.
•	Celery Workers: Procesos dedicados que se ejecutan en segundo plano, escuchando el Message Broker. Cuando reciben una tarea, la ejecutan. Se pueden escalar horizontalmente.
•	Celery Beat: Un componente del Scheduler que se encarga de enviar tareas a la cola de Celery en intervalos programados (ej. cada domingo, cada noche, cada 24 horas).
•	Redis Result Backend: Opcional, para almacenar los resultados de las tareas de Celery, permitiendo al productor consultar el estado o el resultado de una tarea.

10.2. Responsabilidades y Ejemplos de Tareas:
•	Recordatorios de Citas:
◦	Tarea: send_appointment_reminder(appointment_id)
◦	Programación: Celery Beat programa esta tarea para ejecutarse 24 horas antes de cada cita confirmada.
◦	Lógica: Recupera detalles de la cita y el cliente, genera el mensaje y lo envía a través del Notifications Service.
•	Solicitud Semanal de Horarios:
◦	Tarea: request_worker_schedules()
◦	Programación: Celery Beat programa esta tarea cada domingo por la mañana.
◦	Lógica: Itera sobre todas las trabajadoras activas, genera un mensaje proactivo solicitando sus horarios para la semana y lo envía a través del WhatsApp Service.
•	Seguimiento Post-Servicio:
◦	Tarea: send_post_service_followup(appointment_id)
◦	Programación: Celery Beat programa esta tarea para ejecutarse 4 horas después de que una cita se marca como COMPLETED.
◦	Lógica: Envía un mensaje de agradecimiento y consejos de cuidado específicos para el servicio realizado.
•	Recordatorios de Retoque/Mantenimiento:
◦	Tarea: check_retouch_reminders()
◦	Programación: Celery Beat programa esta tarea diariamente.
◦	Lógica: Consulta la base de datos para identificar clientes que se realizaron un servicio específico hace X días (ej. pestañas hace 60 días) y envía un mensaje proactivo con una promoción.
•	Reportes Diarios/Mensuales:
◦	Tarea: generate_daily_worker_report(worker_id, date) / generate_monthly_tenant_report(tenant_id, month)
◦	Programación: Celery Beat programa estas tareas diariamente a las 23:00 y al final de cada mes.
◦	Lógica: Recopila datos de la base de datos, genera el reporte y lo envía a la trabajadora/administrador del tenant.

10.3. Consideraciones de Diseño:
•	Idempotencia: Las tareas deben diseñarse para ser idempotentes, es decir, ejecutar la misma tarea varias veces no debe causar efectos secundarios no deseados. Esto es crucial para la resiliencia en sistemas distribuidos.
•	Manejo de Errores y Reintentos: Celery ofrece mecanismos robustos para el manejo de errores, reintentos automáticos con backoff exponencial y colas de mensajes fallidos (dead-letter queues).
•	Escalabilidad: Los workers de Celery pueden escalarse horizontalmente para manejar un mayor volumen de tareas, y se pueden configurar diferentes colas para priorizar tareas críticas.

11. Estrategias de Seguridad Avanzadas
La seguridad es un aspecto no negociable en una plataforma SaaS. Se implementará una estrategia de seguridad por capas, cubriendo desde la autenticación hasta la infraestructura.

11.1. Autenticación y Autorización:
•	JWT con Cifrado (JWE): Además de la firma (JWS) para verificar la integridad y autenticidad del token, se puede considerar el cifrado (JWE) para proteger la confidencialidad de la información sensible dentro del payload del token, aunque esto añade complejidad y puede no ser necesario si el payload solo contiene IDs y roles.
•	Rotación de Claves JWT: Implementar un mecanismo para rotar periódicamente las claves de firma de JWT para mitigar el riesgo de compromiso de claves a largo plazo.
•	OAuth2/OpenID Connect: Para futuras integraciones con proveedores de identidad externos o para permitir que aplicaciones de terceros accedan a la API de forma segura.
•	RBAC (Role-Based Access Control) Fino: El sistema de roles y permisos se implementará con granularidad fina, permitiendo definir qué acciones puede realizar cada rol sobre qué recursos (ej. un Worker solo puede ver/editar sus propias citas, no las de otras trabajadoras).
•	ABAC (Attribute-Based Access Control): Para escenarios más complejos, se podría evolucionar a ABAC, donde el acceso se basa en atributos del usuario, del recurso y del entorno (ej. un BranchManager solo puede acceder a datos de su sucursal).

11.2. Protección de APIs y Datos:
•	Validación de Entrada y Salida: Validación estricta de todos los datos que entran y salen de la API para prevenir ataques de inyección, XSS, etc. Pydantic en FastAPI facilita esto.
•	Rate Limiting: Implementar límites de tasa a nivel de API Gateway y/o en los servicios individuales para proteger contra ataques de denegación de servicio y fuerza bruta. Se puede usar Redis para almacenar contadores de solicitudes.
•	CORS (Cross-Origin Resource Sharing): Configuración estricta de CORS para permitir solo solicitudes de orígenes de confianza.
•	Protección contra CSRF (Cross-Site Request Forgery): Aunque las APIs RESTful con JWT son menos susceptibles, se deben tomar precauciones, especialmente si se utilizan cookies.
•	Cifrado de Datos en Reposo y en Tránsito:
◦	En Tránsito: Todas las comunicaciones a la API y entre servicios deben usar HTTPS/TLS.
◦	En Reposo: Cifrado a nivel de disco en el VPS y, para datos extremadamente sensibles, cifrado a nivel de columna en la base de datos (aunque esto impacta el rendimiento y la capacidad de búsqueda).
•	Auditoría y Trazabilidad: Registrar todas las acciones críticas de los usuarios y del sistema, incluyendo quién hizo qué, cuándo y desde dónde. Estos logs deben ser inmutables y centralizados.
•	Manejo Seguro de Secretos: Utilizar un sistema de gestión de secretos (ej. HashiCorp Vault, o variables de entorno gestionadas por Coolify/Docker Swarm Secrets) para almacenar claves API, credenciales de base de datos y otros secretos, evitando que estén en el código fuente o en archivos de configuración expuestos.

11.3. Seguridad en la Infraestructura:
•	Firewall: Configurar firewalls (ej. ufw en Linux, o reglas de seguridad en el proveedor de VPS) para permitir solo el tráfico necesario a los puertos de la aplicación y la base de datos.
•	Redes Privadas: Utilizar redes privadas virtuales (VPNs) o redes de overlay de Docker para la comunicación entre servicios, aislando el tráfico interno del público.
•	Hardening del Sistema Operativo: Configurar el sistema operativo del VPS siguiendo las mejores prácticas de seguridad (ej. deshabilitar servicios innecesarios, auditoría de logs, actualizaciones regulares).
•	Escaneo de Vulnerabilidades: Realizar escaneos periódicos de vulnerabilidades en el código, las dependencias y las imágenes Docker.
•	Penetration Testing: Contratar a expertos en seguridad para realizar pruebas de penetración periódicas.

12. Estrategias de Escalabilidad Avanzadas
La escalabilidad es fundamental para el crecimiento de un producto SaaS. La arquitectura está diseñada para escalar horizontalmente en la mayoría de sus componentes.

12.1. Escalabilidad de Componentes:
•	Backend (FastAPI):
◦	Horizontal Scaling: Múltiples instancias de los servicios de FastAPI pueden ejecutarse detrás de un balanceador de carga. Cada instancia es stateless, lo que facilita su adición o eliminación dinámica.
◦	Gunicorn/Uvicorn Workers: Configurar un número óptimo de workers para Uvicorn (servidor ASGI) para aprovechar al máximo los núcleos de la CPU y manejar la concurrencia.
•	Base de Datos (PostgreSQL):
◦	Connection Pooling (PgBouncer): Esencial para gestionar un gran número de conexiones desde el backend, reduciendo la sobrecarga en la base de datos.
◦	Read Replicas: Configurar réplicas de lectura para distribuir la carga de consultas de lectura, que suelen ser la mayoría en muchas aplicaciones. El backend puede dirigir las consultas de lectura a las réplicas y las de escritura al primario.
◦	Sharding/Particionamiento: Para un volumen de datos extremadamente alto, se puede implementar sharding (dividir la base de datos en múltiples servidores) o particionamiento (dividir tablas grandes lógicamente dentro de una misma instancia) basado en tenant_id o rangos de tiempo. Esto requiere una lógica de enrutamiento de consultas en el backend.
◦	Optimización de Consultas: Uso continuo de índices, EXPLAIN ANALYZE y optimización de esquemas para asegurar que las consultas sean eficientes.
•	Redis:
◦	Redis Cluster: Para alta disponibilidad y escalabilidad horizontal, se puede configurar un clúster de Redis que distribuye los datos entre múltiples nodos.
◦	Separación de Uso: Utilizar instancias de Redis separadas para caché y para el broker de mensajes de Celery si la carga es muy alta.
•	Celery Workers:
◦	Horizontal Scaling: Se pueden añadir más workers de Celery para procesar un mayor volumen de tareas asíncronas. Se pueden configurar diferentes colas para diferentes tipos de tareas (ej. high_priority_notifications, marketing_campaigns) y asignar workers específicos a cada cola.
•	Object Storage (S3): Los servicios de almacenamiento de objetos son inherentemente escalables y gestionados por el proveedor, eliminando la preocupación por la escalabilidad del almacenamiento de archivos.

12.2. Escalabilidad por Volumen de Clientes (Revisado):
Escenario	100 Clientes (MVP/Early Growth)	1.000 Clientes (Growth Phase)	10.000+ Clientes (Mature Product)
Backend (FastAPI)	2-4 instancias (CPU 2-4 cores, RAM 4-8GB)	10-20 instancias (CPU 4-8 cores, RAM 8-16GB)	50+ instancias (CPU 8-16 cores, RAM 16-32GB)
Base de Datos (PostgreSQL)	1 instancia (CPU 4 cores, RAM 8GB, SSD) con PgBouncer	1 instancia primaria (CPU 8 cores, RAM 16GB, NVMe SSD) + 2-3 réplicas de lectura	Clúster PostgreSQL con sharding (ej. Citus Data) o particionamiento, múltiples réplicas de lectura, optimización avanzada.
Redis	1 instancia (CPU 2 cores, RAM 4GB)	2-3 instancias (CPU 4 cores, RAM 8GB)	Redis Cluster (3+ nodos)
Celery Workers	2-4 workers (CPU 2 cores, RAM 4GB)	10-20 workers (CPU 4 cores, RAM 8GB)	50+ workers, con colas dedicadas y priorización
Despliegue	Docker Compose + Coolify en 1-2 VPS Hetzner	Docker Compose + Coolify en 5-10 VPS Hetzner, o migración a Kubernetes/Docker Swarm	Kubernetes en un proveedor de nube (AWS EKS, GCP GKE, Azure AKS) con autoescalado.
Observabilidad	Logs centralizados, métricas básicas	Monitoreo APM completo, trazas distribuidas, alertas avanzadas	Observabilidad proactiva con IA, análisis de anomalías, auto-reparación.
13. DevOps y Estrategias de Despliegue
Una estrategia DevOps robusta es esencial para la entrega continua de valor, la estabilidad del sistema y la eficiencia operativa.

13.1. Pipeline CI/CD (GitHub Actions):
graph TD
    A[Developer Push to GitHub] --> B(GitHub Actions Workflow Trigger)
 
    subgraph CI Pipeline
        B -- Linting & Formatting --> C(Code Quality Checks)
        C -- Unit & Integration Tests --> D(Automated Testing)
        D -- Build Docker Images --> E(Docker Build)
        E -- Push to Container Registry --> F(Docker Hub / GitHub Container Registry)
    end
 
    subgraph CD Pipeline
        F -- Deploy to Staging --> G(Coolify / SSH to VPS)
        G -- Run E2E Tests --> H(Automated E2E Testing)
        H -- Manual Review / Approval --> I(Human Approval)
        I -- Deploy to Production --> J(Coolify / SSH to VPS)
        J -- Health Checks & Smoke Tests --> K(Post-Deployment Verification)
        K -- Rollback if Failed --> L(Automated Rollback)
    end
 
    F -- Optional: Security Scan --> M(Vulnerability Scanning)
    M -- Report --> B

Pasos Clave:

•	Integración Continua (CI): Cada push a una rama de desarrollo o pull request dispara un workflow que realiza:
◦	Análisis de Calidad de Código: Linting (ej. Flake8, Black), formateo (ej. Black), análisis estático (ej. Pylint, Bandit).
◦	Pruebas Automatizadas: Ejecución de pruebas unitarias, de integración y de contrato (para APIs).
◦	Construcción de Imágenes Docker: Creación de imágenes Docker para cada servicio del backend.
◦	Escaneo de Vulnerabilidades: Escaneo de las imágenes Docker y dependencias en busca de vulnerabilidades conocidas.
◦	Publicación: Las imágenes Docker se publican en un registro de contenedores (ej. Docker Hub, GitHub Container Registry).
•	Despliegue Continuo (CD): Después de una integración exitosa y la aprobación manual (para producción):
◦	Despliegue a Staging: Las nuevas imágenes se despliegan automáticamente en un entorno de staging (pre-producción) utilizando Coolify o scripts SSH/Ansible.
◦	Pruebas End-to-End (E2E): Ejecución de pruebas E2E automatizadas en el entorno de staging para verificar la funcionalidad completa del sistema.
◦	Aprobación Manual: Para el despliegue en producción, se requiere una aprobación manual para garantizar la calidad.
◦	Despliegue a Producción: Las imágenes se despliegan en el entorno de producción.
◦	Verificación Post-Despliegue: Ejecución de health checks y smoke tests para asegurar que la aplicación se ha desplegado correctamente y funciona como se espera.
◦	Rollback Automatizado: En caso de fallo en el despliegue o en las pruebas post-despliegue, el sistema debe ser capaz de revertir automáticamente a la versión anterior estable.

13.2. Estrategia de Despliegue con Coolify y Hetzner VPS:
•	Servidor Único (Inicial): Para el MVP y las primeras fases de crecimiento, un único VPS de Hetzner con Coolify puede alojar todos los servicios (FastAPI, PostgreSQL, Redis, Celery Workers). Coolify simplifica la gestión de Docker Compose, SSL (Let's Encrypt), dominios y despliegues.
•	Múltiples Servidores (Crecimiento): A medida que la carga aumenta, se pueden añadir más VPS de Hetzner. Coolify puede gestionar despliegues en múltiples servidores, o se puede migrar a Docker Swarm o Kubernetes para una orquestación más avanzada y autoescalado.
•	Blue/Green Deployment o Canary Releases: Para minimizar el tiempo de inactividad y el riesgo durante los despliegues, se implementarán estrategias como Blue/Green Deployment (desplegar la nueva versión en un entorno separado y luego cambiar el tráfico) o Canary Releases (desplegar la nueva versión a un pequeño subconjunto de usuarios primero).

14. Roadmap de Desarrollo Detallado
El roadmap se presenta con mayor granularidad, incluyendo tareas específicas y una estimación de esfuerzo en puntos de historia (SP) o días, asumiendo un equipo de desarrollo ágil.

Fase	Objetivo	Duración Estimada (Sprints/Semanas)	Entregables Clave	Dependencias	Prioridad	Riesgos	SP Estimados
Fase 0: Setup & Core Infra	Configurar entorno, CI/CD, base de datos y estructura de proyecto.	1 semana	Repositorio Git, Docker Compose funcional, FastAPI "Hello World", DB PostgreSQL configurada, Alembic inicializado, pipeline CI/CD básico.	Ninguna	Alta	Configuración de entorno, problemas de compatibilidad.	40
Fase 1: Autenticación & Multi-tenancy	Implementar Auth Service, Users Service y Tenants Service con aislamiento de datos.	2 semanas	Registro/Login de usuarios, gestión de tenants, JWT, middleware de tenant_id, CRUD de usuarios/tenants.	Fase 0	Alta	Complejidad en el aislamiento de datos, seguridad de JWT, diseño de roles.	80
Fase 2: Gestión de Trabajadoras & Servicios	Desarrollar Workers Service y Services Service.	1.5 semanas	CRUD de trabajadoras (con especialidades), CRUD de servicios, asignación de trabajadoras a sucursales.	Fase 1	Media-Alta	Definición detallada de especialidades y servicios.	60
Fase 3: Gestión de Clientes & Citas (Core)	Implementar Clients Service, Calendar Service y Appointments Service (lógica central).	3 semanas	CRUD de clientes, creación/modificación/cancelación de citas, validación de disponibilidad, integración con Google Calendar (solo lectura).	Fase 1, Fase 2	Alta	Lógica de disponibilidad compleja, concurrencia en reservas, UX de calendario.	120
Fase 4: Integración WhatsApp (Básico)	Habilitar envío/recepción de mensajes básicos vía WhatsApp Service.	1 semana	Webhook de Evolution API, envío de mensajes de texto, registro de conversaciones.	Fase 3, WhatsApp Service	Media	Fiabilidad de la Evolution API, manejo de errores.	40
Fase 5: Integración IA (Interpretación)	Integrar AI Service para interpretar mensajes de WhatsApp.	2 semanas	Interpretación de intención y entidades de mensajes de texto, actualización de horarios de trabajadoras (conversacional).	Fase 4, AI Service	Media-Alta	Precisión de la IA, prompt engineering, manejo de ambigüedad.	80
Fase 6: Validación de Pagos con OCR	Implementar Payments Service y OCR Service para validación de adelantos.	2.5 semanas	Envío de instrucciones de pago, procesamiento de vouchers con OCR, validación de datos, confirmación automática de citas.	Fase 3, Payments Service, OCR Service	Media-Alta	Precisión del OCR, detección de fraudes, integración con pasarela de pago (Yape).	100
Fase 7: Scheduler & Tareas Asíncronas	Desarrollar Scheduler Service con Celery/Redis para tareas recurrentes.	2 semanas	Recordatorios de citas, reportes diarios para trabajadoras, solicitud semanal de horarios, seguimiento post-servicio.	Fase 3, Notifications Service	Media	Gestión de tareas asíncronas, fiabilidad del Scheduler, manejo de errores.	80
Fase 8: Marketing & Fidelización	Implementar Marketing Service para campañas segmentadas.	2.5 semanas	Publicidad masiva segmentada (por servicio, última visita), recordatorios de retoque, mensajes de agradecimiento post-servicio.	Fase 3, Fase 7, Marketing Service	Media	Segmentación compleja, personalización de mensajes, rendimiento de campañas.	100
Fase 9: Reportes & Analíticas	Desarrollar Reports Service y Analytics Service.	2 semanas	Reportes mensuales de ingresos, clientes atendidos, servicios más vendidos, dashboard básico.	Fase 3	Media	Complejidad de los cálculos, visualización de datos, rendimiento de consultas.	80
Fase 10: Frontend (MVP)	Desarrollar la interfaz de usuario mínima viable para administradores y trabajadoras.	4 semanas	Panel de administración (CRUD de tenants, branches, workers, services), panel de trabajadoras (gestión de citas, horarios), interfaz de reservas para clientes.	Todas las fases de backend	Alta	Diseño UX/UI, integración con API, rendimiento del frontend.	160
Fase 11: Pruebas Integrales & Optimización	Pruebas de seguridad, rendimiento, carga y optimización general.	2 semanas	Pruebas de carga, penetration testing, optimización de consultas SQL, caching, revisión de seguridad.	Todas las fases	Alta	Detección de bugs tardía, cuellos de botella de rendimiento, vulnerabilidades.	80
Total SP Estimados: ~1080 SP (aproximadamente 27 semanas o 6-7 meses para un equipo pequeño/mediano, asumiendo 40 SP/semana).

15. Desarrollo Asistido por IA: Integración en el Workflow
La integración de herramientas de IA no es solo una conveniencia, sino una estrategia para maximizar la eficiencia del equipo de ingeniería, reducir el tiempo de comercialización y mejorar la calidad del software. Se propone un workflow donde la IA complementa y potencia las capacidades humanas.

15.1. Roles de las Herramientas de IA:
•	ChatGPT Agente (o LLM de alto nivel):
◦	Fase de Diseño y Arquitectura: Actúa como un co-arquitecto o consultor técnico. Se utiliza para:
•	Validación de Diseños: Presentar propuestas de arquitectura (ej. esquemas de DB, flujos de datos) y obtener feedback crítico, identificar posibles cuellos de botella o vulnerabilidades.
•	Exploración de Alternativas: Evaluar diferentes patrones de diseño, stacks tecnológicos o soluciones para problemas complejos, con justificaciones técnicas.
•	Generación de Ideas: Brainstorming para optimizaciones de rendimiento, estrategias de escalabilidad o nuevas funcionalidades.
•	Revisión Técnica: Análisis de secciones de código o diseños para identificar errores lógicos, ineficiencias o incumplimientos de buenas prácticas.
◦	Output: Documentos de diseño, análisis de trade-offs, recomendaciones técnicas, diagramas conceptuales.
•	Cursor (o IDEs con capacidades de IA avanzadas):
◦	Fase de Codificación: Es el asistente de codificación personal de cada desarrollador. Se utiliza para:
•	Autocompletado Inteligente: Sugerencias de código contextuales que aceleran la escritura.
•	Generación de Boilerplate: Creación rápida de clases, funciones, métodos, modelos Pydantic/SQLAlchemy a partir de descripciones o esquemas.
•	Refactorización Asistida: Sugerencias para mejorar la estructura del código, renombrar variables, extraer funciones.
•	Depuración: Análisis de trazas de errores y sugerencias para posibles soluciones.
•	Generación de Pruebas Unitarias: Creación de esqueletos o implementaciones completas de pruebas para funciones existentes.
◦	Output: Código fuente de alta calidad, pruebas unitarias, refactorizaciones.
•	OpenHands (o Agentes de Desarrollo Autónomos):
◦	Fase de Implementación y Mantenimiento: Actúa como un ingeniero de software autónomo para tareas bien definidas. Se utiliza para:
•	Implementación de Módulos Completos: A partir de una especificación detallada (ej. "implementar el CRUD para el Clients Service con validación Pydantic y persistencia en PostgreSQL"), OpenHands puede generar el código completo del módulo, incluyendo modelos, esquemas, servicios, routers y repositorios.
•	Generación Exhaustiva de Pruebas: Escribir pruebas de integración y end-to-end para funcionalidades existentes, asegurando una cobertura robusta.
•	Refactorización a Gran Escala: Aplicar patrones de diseño o cambios arquitectónicos a través de múltiples archivos y módulos de forma consistente.
•	Automatización de Tareas Repetitivas: Scripts para migraciones de datos, generación de documentación, análisis de logs, etc.
•	Resolución de Bugs: Identificar y corregir errores en el código base, incluso en componentes complejos.
◦	Output: Módulos de código funcionales, suites de pruebas completas, refactorizaciones aplicadas, scripts de automatización.

15.2. Workflow Integrado de Desarrollo con IA:
17	Diseño (Humano + ChatGPT Agente): El equipo de ingeniería, en colaboración con ChatGPT Agente, define la arquitectura de alto nivel, el modelo de datos y los contratos de API. ChatGPT Agente valida ideas y explora alternativas.
18	Especificación (Humano): Los ingenieros detallan las especificaciones para cada módulo o funcionalidad, incluyendo modelos de datos, lógica de negocio y endpoints de API.
19	Implementación (OpenHands + Cursor):
◦	OpenHands toma las especificaciones y genera el esqueleto inicial del módulo, incluyendo modelos, esquemas, servicios y routers.
◦	Los desarrolladores utilizan Cursor para refinar el código generado, añadir lógica de negocio específica y escribir pruebas unitarias, beneficiándose del autocompletado y las sugerencias de IA.
20	Pruebas (OpenHands + Humano): OpenHands genera pruebas de integración y E2E. Los desarrolladores revisan y complementan estas pruebas, y realizan pruebas manuales.
21	Revisión de Código (Humano + ChatGPT Agente): Los ingenieros revisan el código. ChatGPT Agente puede realizar una revisión automatizada adicional para identificar patrones de código problemáticos o posibles mejoras.
22	Despliegue (CI/CD Automatizado): El pipeline CI/CD se encarga del despliegue, con monitoreo continuo.
23	Mantenimiento y Refactorización (OpenHands + Cursor): OpenHands puede asistir en la refactorización de código legado o en la implementación de nuevas características, mientras que Cursor ayuda en las tareas diarias de mantenimiento.

Este enfoque permite que los ingenieros se centren en la creatividad, la resolución de problemas complejos y la toma de decisiones estratégicas, delegando las tareas repetitivas y de bajo nivel a las herramientas de IA.

16. Mantenimiento, Observabilidad y Futuras Ampliaciones
16.1. Mantenimiento y Observabilidad:
La mantenibilidad de un sistema SaaS es tan crítica como su desarrollo inicial. Se implementará una estrategia integral de observabilidad para garantizar la salud y el rendimiento del sistema.

•	Monitoreo de Infraestructura y Aplicación:
◦	Métricas: Utilizar Prometheus para recopilar métricas de todos los componentes (CPU, RAM, disco, red de VPS; latencia, errores, rendimiento de FastAPI; uso de CPU/memoria de PostgreSQL/Redis; tasas de éxito/fallo de Celery). Grafana se usará para visualizar estas métricas en dashboards interactivos.
◦	Logs Centralizados: Implementar un ELK Stack (Elasticsearch, Logstash, Kibana) o Grafana Loki para centralizar todos los logs de la aplicación y la infraestructura. Esto facilita la búsqueda, el análisis y la depuración de problemas.
◦	Trazas Distribuidas: Implementar OpenTelemetry (o Jaeger/Zipkin) para trazas distribuidas, permitiendo seguir una solicitud a través de múltiples servicios y componentes, crucial para diagnosticar cuellos de botella en arquitecturas distribuidas.
•	Alertas: Configurar alertas (ej. Alertmanager con Prometheus) para notificar al equipo de operaciones sobre anomalías, errores críticos, umbrales de rendimiento excedidos o fallos de seguridad.
•	Gestión de Errores: Integrar una herramienta de gestión de errores (ej. Sentry) para capturar y reportar excepciones en tiempo real, con información contextual para una depuración rápida.
•	Actualizaciones y Parches: Establecer un proceso automatizado para aplicar parches de seguridad y actualizaciones a las dependencias, librerías y el sistema operativo. Utilizar herramientas como Dependabot (GitHub) para monitorear dependencias.
•	Documentación Viva: Mantener la documentación técnica (arquitectura, APIs, modelo de datos) actualizada automáticamente donde sea posible (ej. OpenAPI docs de FastAPI) y manualmente para decisiones de diseño y runbooks.

16.2. Futuras Ampliaciones Estratégicas:
La arquitectura modular de Glowlab permite una expansión flexible para incorporar nuevas funcionalidades y adaptarse a las demandas del mercado.

•	Integración Omnicanal: Ampliar el Notifications Service para soportar otros canales de comunicación como Email (SendGrid, Mailgun), SMS (Twilio) o incluso un chatbot web integrado en el frontend.
•	Sistema de Fidelización Avanzado: Implementar un módulo de Loyalty Program con puntos, niveles de membresía, recompensas personalizadas y programas de referidos para aumentar la retención de clientes.
•	Gestión de Inventario y Productos: Para salones que venden productos, un módulo de Inventory Management que gestione el stock, proveedores y ventas.
•	Terminal de Punto de Venta (POS): Un módulo POS integrado para gestionar transacciones en el local, incluyendo ventas de productos y servicios, pagos y cierres de caja.
•	Análisis Predictivo y Personalización: Utilizar el Analytics Service y el AI Service para desarrollar modelos predictivos que sugieran servicios a clientes, optimicen horarios, prevean la demanda o identifiquen clientes en riesgo de abandono.
•	Integración con Calendarios Externos (Bidireccional): Permitir a las trabajadoras sincronizar sus calendarios personales (ej. Google Calendar, Outlook Calendar) de forma bidireccional con el sistema, gestionando su disponibilidad de forma más fluida y evitando conflictos.
•	Personalización Avanzada por Tenant: Ofrecer a cada empresa la capacidad de personalizar aún más la experiencia de su cliente (ej. temas de la interfaz, plantillas de mensajes de WhatsApp, reglas de negocio específicas).
•	Marketplace de Servicios/Plugins: Un ecosistema donde terceros puedan desarrollar y ofrecer extensiones o integraciones para la plataforma Glowlab.

17. Conclusión
Este informe de ingeniería de software establece una base sólida y detallada para el desarrollo de la plataforma SaaS Glowlab. Al adoptar una arquitectura limpia, un stack tecnológico moderno y estrategias avanzadas de seguridad, escalabilidad y DevOps, el proyecto está posicionado para construir un producto robusto, eficiente y adaptable. La inversión en un diseño técnico riguroso desde el inicio asegurará la capacidad de la plataforma para crecer, innovar y satisfacer las demandas de un mercado de servicios en constante evolución, transformando la visión de Glowlab en una realidad comercialmente exitosa.














ROADMAP PARA HACER GLOWLAB CON ANTIGRAVITY
🟣 FASE 0 — Preparación del entorno
Objetivo
Dejar Antigravity listo para trabajar sobre un proyecto real.
Paso 0.1: Crear el repositorio
En GitHub:
glowlab-platform
Estructura inicial:
glowlab-platform/
│
├── backend/
├── frontend/
├── infrastructure/
├── docs/
├── docker-compose.yml
├── README.md
└── .gitignore
Paso 0.2: Abrir el proyecto en Antigravity
Le das acceso al repositorio local.
Su primera tarea debe ser solamente analizar, no programar todavía.
Prompt conceptual:
Analiza el proyecto Glowlab. Es una plataforma SaaS multi-tenant para salones de belleza. Antes de modificar código, inspecciona la estructura del repositorio y propón una arquitectura de monolito modular basada en Clean Architecture. No implementes código todavía. Genera la documentación técnica en /docs/architecture.md.
Entregable
✓ Repositorio creado
✓ Proyecto abierto en Antigravity
✓ Git configurado
✓ Arquitectura documentada
✓ No hay funcionalidades todavía
________________________________________
🟣 FASE 1 — Arquitectura base
Tu propio informe propone primero preparar la arquitectura, estructura de carpetas, configuración, manejo de errores, variables de entorno y logging. 
Aquí Antigravity sí puede avanzar bastante rápido.
Estructura que yo usaría
backend/
│
├── app/
│   ├── main.py
│   │
│   ├── core/
│   │   ├── config/
│   │   ├── security/
│   │   ├── database/
│   │   ├── exceptions/
│   │   └── logging/
│   │
│   ├── modules/
│   │   ├── auth/
│   │   ├── tenants/
│   │   ├── users/
│   │   ├── branches/
│   │   ├── workers/
│   │   ├── services/
│   │   ├── clients/
│   │   ├── appointments/
│   │   ├── schedules/
│   │   ├── whatsapp/
│   │   ├── ai/
│   │   └── notifications/
│   │
│   ├── infrastructure/
│   │   ├── repositories/
│   │   ├── messaging/
│   │   └── external_services/
│   │
│   └── api/
│
├── tests/
├── alembic/
├── requirements.txt
└── Dockerfile
En cada módulo
Por ejemplo:
appointments/
│
├── domain/
│   ├── entities/
│   ├── repositories/
│   └── services/
│
├── application/
│   ├── use_cases/
│   └── dto/
│
├── infrastructure/
│   ├── models/
│   └── repositories/
│
└── presentation/
    └── routes/
Antigravity debe implementar
•	FastAPI. 
•	Configuración .env. 
•	PostgreSQL. 
•	SQLAlchemy. 
•	Alembic. 
•	Docker. 
•	Docker Compose. 
•	Health check. 
•	Logging. 
•	Manejo global de errores. 
•	Pytest. 
Regla importante para Antigravity
Una tarea por vez.
No:
"Construye toda la arquitectura de Glowlab."
Mejor:
"Implementa únicamente la configuración base de FastAPI, PostgreSQL, SQLAlchemy y Docker. No implementes ningún módulo de negocio. Ejecuta las pruebas y verifica que /health responda correctamente."
Entregable
Backend funcionando
↓
docker compose up
↓
FastAPI funcionando
↓
PostgreSQL conectado
↓
Alembic funcionando
↓
Health check
↓
Tests básicos
________________________________________
🟣 FASE 1.5 — DISEÑO DE DOMINIO
Esta fase me parece fundamental en tu proyecto y, de hecho, aparece añadida explícitamente en tu documento como “Diseño de Dominio (Domain-Driven Design)”. 
Aquí todavía no programes
Usa Antigravity para analizar el dominio.
Primero: entidades
Tenant
Branch
User
Worker
Client
Service
Appointment
Schedule
Conversation
Message
Payment
Voucher
Notification
Campaign
Reminder
AI Request
AI Response
Audit Log
RolePermission
Subscription
Plan
Antigravity debe generar documentación
Por ejemplo:
docs/domain/
├── entities.md
├── aggregates.md
├── business_rules.md
├── bounded_contexts.md
├── use_cases.md
└── domain_events.md
Después definir los Bounded Contexts
Yo los dividiría inicialmente así:
1. Identity
Users
Roles
Permissions
Authentication
2. Tenant Management
Tenant
Subscription
Plan
Branch
3. Business Operations
Workers
Services
Schedules
Clients
4. Booking
Availability
Appointments
Cancellations
Confirmations
5. Conversations
WhatsApp
Messages
Conversations
AI Interpretation
6. Payments
Payments
Advances
Vouchers
OCR
7. Automation
Reminders
Scheduled Jobs
Notifications
8. Growth
Campaigns
Marketing
Analytics
Reports
Entregable
Antes de escribir la lógica principal, debes tener:
✓ Diagrama del dominio
✓ Entidades
✓ Relaciones
✓ Reglas de negocio
✓ Casos de uso
✓ Eventos
✓ Bounded Contexts
________________________________________
🟣 FASE 2 — BASE DE DATOS Y MULTI-TENANCY
Esta es una de las fases más delicadas.
El documento establece un modelo inicial de base de datos compartida y esquema compartido con aislamiento mediante tenant_id. 
Implementación
Primero:
Tenant
Luego:
Branch
User
Role
Después:
Worker
Client
Service
Schedule
Appointment
Regla de oro
Toda entidad perteneciente a una empresa debe tener:
tenant_id
Ejemplo:
Tenant A
 ├── Client 1
 ├── Client 2
 └── Appointment 1

Tenant B
 ├── Client 3
 └── Appointment 2
Tenant A jamás debe poder consultar Client 3.
Antigravity debe implementar y probar
1. TenantContext
2. Middleware
3. Extracción de tenant_id
4. Filtros automáticos
5. Validación de aislamiento
6. Tests multi-tenant
Test obligatorio
Usuario Tenant A
↓
Intenta consultar recurso Tenant B
↓
403 / 404
No avances hasta que esto funcione.
________________________________________
🟣 FASE 3 — AUTENTICACIÓN Y ROLES
Aquí construyes:
Registro
Login
Logout
Refresh Token
JWT
Roles
Permisos
Roles iniciales:
PLATFORM_ADMIN
OWNER
ADMIN
STAFF
WORKER
Flujo
Usuario
   ↓
Login
   ↓
JWT
   ↓
user_id
tenant_id
role
   ↓
Tenant Context
El roadmap original del informe también prioriza esta fase antes de los módulos operativos. 
Antigravity
Prompt por tarea:
Implementa únicamente el módulo Auth siguiendo la arquitectura existente. Debe soportar registro de Tenant + Owner inicial, login y JWT. No modifiques otros módulos. Escribe tests unitarios e integración. Ejecuta los tests antes de finalizar.
Entregable
✓ Register
✓ Login
✓ JWT
✓ Refresh
✓ Roles
✓ Tests
________________________________________
🟣 FASE 4 — CONFIGURACIÓN DEL NEGOCIO
Ahora el dueño puede configurar su salón.
Módulos
Branches
Crear sucursal
Editar sucursal
Horario
Zona horaria
Workers
Nombre
Teléfono
Especialidades
Sucursal
Estado
Services
Nombre
Descripción
Precio
Duración
Esto coincide con la fase de gestión de trabajadoras y servicios del roadmap original. 
Flujo
Tenant
   ↓
Branch
   ↓
Workers
   ↓
Services
Aquí Antigravity construye
Primero backend:
CRUD Branch
Luego:
CRUD Worker
Después:
CRUD Service
No le des los tres módulos en una sola instrucción.
________________________________________
🟣 FASE 5 — CLIENTES Y HORARIOS
Construyes:
Client
Schedule
Availability
Client
Nombre
Teléfono
Preferencias
Última visita
Historial
Schedule
Trabajadora
↓
Lunes
09:00 - 18:00

Martes
09:00 - 18:00
Motor de disponibilidad
Debe responder:
GET /availability
Resultado:
{
  "date": "2026-08-15",
  "worker_id": "...",
  "available_slots": [
    "10:00",
    "11:00",
    "15:00"
  ]
}
________________________________________
🟣 FASE 6 — EL CORE: SISTEMA DE CITAS
Esta es la fase más importante del MVP.
El roadmap del documento identifica precisamente clientes, calendario y citas como el núcleo de la lógica de negocio. 
Flujo
Cliente
   ↓
Selecciona servicio
   ↓
Selecciona trabajadora
   ↓
Sistema consulta disponibilidad
   ↓
Selecciona horario
   ↓
Cita PENDING
   ↓
Confirmación
   ↓
CONFIRMED
   ↓
COMPLETED
Estados:
PENDING
CONFIRMED
COMPLETED
CANCELLED
NO_SHOW
Regla crítica
Antigravity debe crear tests para evitar:
Dos citas
↓
Misma trabajadora
↓
Mismo horario
Esto debe ser imposible incluso con dos solicitudes simultáneas.
Antes de pasar a WhatsApp
Debes poder hacer una reserva completa usando Swagger:
1. Crear cliente
2. Consultar disponibilidad
3. Crear cita
4. Confirmar
5. Cancelar
6. Completar
________________________________________
🟣 FASE 7 — FRONTEND MVP
Yo adelantaría el frontend antes de implementar IA, OCR y marketing.
Tu documento original coloca el frontend después de casi todo el backend, pero para trabajar solo con Antigravity considero más práctico construir un frontend MVP apenas el core de citas esté estable.
El documento contempla un panel de administración, panel de trabajadoras e interfaz de reservas. 
Next.js
Primera versión:
Login
│
├── Dashboard
├── Calendario
├── Citas
├── Clientes
├── Trabajadoras
├── Servicios
└── Configuración
Primera meta visual
Que puedas entrar a:
glowlab.com/dashboard
Y gestionar un salón completo.
Regla para Antigravity
Primero:
UI con datos mock
Luego:
Conectar API
Después:
Autenticación real
________________________________________
🟣 FASE 8 — INTEGRACIÓN CON EVOLUTION API
Una vez que las citas funcionan desde el panel:
Cliente
   ↓
WhatsApp
   ↓
Evolution API
   ↓
Webhook
   ↓
Glowlab Backend
Primera versión sin IA.
Solo:
Recibir mensaje
Guardar conversación
Responder mensaje básico
El documento plantea exactamente el webhook, envío de mensajes y registro de conversaciones como una fase inicial de la integración de WhatsApp. 
Prueba inicial
Cliente:
"Hola"

Sistema:
"Hola 👋 ¿En qué podemos ayudarte?"
Después:
Cliente:
"Quiero una cita"
Aún puedes responder con un flujo simple.
________________________________________
🟣 FASE 9 — IA PARA EL CHATBOT
Aquí recién introduces Gemini, OpenAI o Claude.
Pero la IA no debe manejar la base de datos directamente.
El documento es muy claro en esto: la IA debe interpretar lenguaje y devolver intención y entidades estructuradas; la lógica de negocio toma las decisiones. 
Arquitectura
WhatsApp
   ↓
Mensaje
   ↓
AI Service
   ↓
{
  intent,
  entities,
  confidence
}
   ↓
Business Logic
   ↓
Respuesta
Ejemplo:
Usuario:
"Quiero hacerme las uñas mañana con María"
IA:
{
  "intent": "book_appointment",
  "entities": {
    "service": "uñas",
    "date": "2026-08-10",
    "worker": "María"
  },
  "confidence": 0.94
}
Después el backend pregunta:
¿Existe María?
¿Hace ese servicio?
¿Está disponible?
¿Hay conflicto?
La IA interpreta. El backend decide.
________________________________________
🟣 FASE 10 — AGENTE DE CITAS COMPLETO
Ahora unes todo.
Conversación
Cliente:
Hola, quiero una cita
       ↓
IA detecta intención
       ↓
Backend pregunta servicio
       ↓
Cliente responde
       ↓
IA extrae servicio
       ↓
Backend consulta trabajadoras
       ↓
Cliente selecciona
       ↓
Backend consulta disponibilidad
       ↓
Cliente selecciona hora
       ↓
Sistema muestra resumen
       ↓
Cliente confirma
       ↓
Appointment CONFIRMED
Esta es, para mí, la primera gran versión comercial de Glowlab.
MVP REAL
En este punto ya tienes:
✓ SaaS
✓ Multi-tenant
✓ Usuarios
✓ Salones
✓ Trabajadoras
✓ Servicios
✓ Clientes
✓ Horarios
✓ Citas
✓ Panel web
✓ WhatsApp
✓ IA
✓ Chatbot de reservas
Yo intentaría conseguir el primer cliente piloto aquí.
No esperaría a tener OCR, campañas, analítica avanzada y todos los módulos del documento.
________________________________________
🟣 FASE 11 — PAGOS Y VOUCHERS
Ahora:
Adelanto
↓
Yape
↓
Cliente envía voucher
↓
WhatsApp recibe imagen
↓
Storage
↓
OCR
↓
Validación
↓
Pago confirmado
El informe contempla específicamente el procesamiento de adelantos y validación OCR de vouchers. 
Yo haría primero:
Versión 1
Voucher
↓
Revisión manual
↓
Administrador confirma
Versión 2
OCR
↓
Extracción automática
↓
Validación
Esto reduce bastante la complejidad inicial.
________________________________________
🟣 FASE 12 — AUTOMATIZACIONES
Aquí reemplazas definitivamente la lógica que antes pensabas hacer con n8n.
Tu documento plantea Celery/Redis para el procesamiento asíncrono y tareas programadas. 
Implementas:
Recordatorios
24 horas antes
↓
Enviar WhatsApp
Post-servicio
4 horas después
↓
Mensaje de agradecimiento
Retoque
Servicio realizado
↓
Esperar X días
↓
Enviar recordatorio
Solicitud de horarios
Domingo
↓
Solicitar disponibilidad semanal
________________________________________
🟣 FASE 13 — MARKETING INTELIGENTE
Ahora sí:
Clientes que no vienen hace 60 días
↓
Segmentación
↓
Campaña
↓
WhatsApp
Segmentos:
ALL_CLIENTS
SERVICE_BASED
LAST_VISIT_BASED
WORKER_SPECIFIC
Ejemplo:
Clientes que se hicieron pestañas hace 50-60 días.
↓
"Hola María ✨ Ya es momento de tu retoque. Esta semana tenemos disponibilidad..."
________________________________________
🟣 FASE 14 — REPORTES Y ANALÍTICA
Dashboard:
Ingresos del mes
Citas realizadas
No shows
Servicios más vendidos
Trabajadora con más reservas
Clientes recurrentes
Ingresos por sucursal
Conversión de campañas
El documento contempla reportes mensuales, clientes atendidos, servicios más vendidos y un dashboard básico como entregables de esta capa. 
________________________________________
🟣 FASE 15 — PRODUCCIÓN Y CALIDAD
Finalmente:
GitHub
   ↓
Push
   ↓
GitHub Actions
   ↓
Tests
   ↓
Docker Build
   ↓
Staging
   ↓
Tests E2E
   ↓
Aprobación
   ↓
Producción
Tu informe plantea CI/CD, staging, pruebas E2E, verificación post-despliegue y rollback. 
Para el inicio, un único VPS con Coolify puede alojar el MVP y los primeros componentes: FastAPI, PostgreSQL, Redis y workers. 
________________________________________
🔥 EL ORDEN QUE YO REALMENTE SEGUIRÍA
Etapa A — Fundación
Fase 0 → Entorno y GitHub
Fase 1 → Arquitectura base
Fase 1.5 → Diseño de dominio
Fase 2 → Base de datos multi-tenant
Fase 3 → Auth y permisos
Etapa B — Producto Core
Fase 4 → Salón, trabajadoras y servicios
Fase 5 → Clientes y horarios
Fase 6 → Motor de citas
Fase 7 → Frontend MVP
Etapa C — Automatización inteligente
Fase 8 → WhatsApp básico
Fase 9 → IA interpretativa
Fase 10 → Agente de citas completo
Etapa D — Funciones premium
Fase 11 → Pagos/OCR
Fase 12 → Automatizaciones
Fase 13 → Marketing
Fase 14 → Analítica
Etapa E — Escalamiento
Fase 15 → Testing, seguridad y producción

