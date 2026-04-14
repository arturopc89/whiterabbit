-- ═══════════════════════════════════════════════════════════
-- WhiteRabbit — Migración SQLite → Supabase PostgreSQL
-- Ejecutar en: Supabase Dashboard → SQL Editor → New Query
-- ═══════════════════════════════════════════════════════════

-- 1. MESSAGES (existente en SQLite → migrada)
CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    read        BOOLEAN DEFAULT FALSE,
    replied     BOOLEAN DEFAULT FALSE,
    reply_text  TEXT,
    replied_at  TIMESTAMPTZ
);

CREATE INDEX idx_messages_created ON messages (created_at DESC);
CREATE INDEX idx_messages_email ON messages (email);
CREATE INDEX idx_messages_unread ON messages (read) WHERE read = FALSE;

-- 2. DIAGNOSTICS (existente en SQLite → migrada)
CREATE TABLE IF NOT EXISTS diagnostics (
    id             BIGSERIAL PRIMARY KEY,
    url            TEXT NOT NULL,
    email          TEXT,  -- NUEVO: email del que pidió el diagnóstico (para el gate)
    health_score   INTEGER,
    report_json    JSONB,  -- MEJORA: JSONB en vez de TEXT para queries sobre el reporte
    crawl_summary  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_diagnostics_created ON diagnostics (created_at DESC);
CREATE INDEX idx_diagnostics_url ON diagnostics (url);
CREATE INDEX idx_diagnostics_email ON diagnostics (email) WHERE email IS NOT NULL;

-- 3. LEADS (NUEVO — pipeline de ventas)
-- Unifica contactos del formulario, diagnósticos y chatbot en un solo lead
CREATE TABLE IF NOT EXISTS leads (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    name        TEXT,
    phone       TEXT,
    company     TEXT,
    source      TEXT NOT NULL DEFAULT 'contact_form',  -- contact_form | diagnostic | chatbot | manual
    status      TEXT NOT NULL DEFAULT 'new',  -- new | contacted | proposal | client | lost
    notes       TEXT,
    score       INTEGER DEFAULT 0,  -- lead scoring (0-100)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    contacted_at TIMESTAMPTZ,

    CONSTRAINT valid_status CHECK (status IN ('new', 'contacted', 'proposal', 'client', 'lost')),
    CONSTRAINT valid_source CHECK (source IN ('contact_form', 'diagnostic', 'chatbot', 'manual', 'meta_ads', 'referral'))
);

CREATE UNIQUE INDEX idx_leads_email ON leads (email);
CREATE INDEX idx_leads_status ON leads (status);
CREATE INDEX idx_leads_created ON leads (created_at DESC);

-- 4. EMAIL_CAPTURES (NUEVO — gate del diagnóstico)
-- Cada vez que alguien pone su email para usar el diagnóstico
CREATE TABLE IF NOT EXISTS email_captures (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    url_diagnosed TEXT,  -- la URL que quiso diagnosticar
    source_page TEXT DEFAULT 'landing',  -- landing | blog | ads
    utm_source  TEXT,
    utm_medium  TEXT,
    utm_campaign TEXT,
    ip_hash     TEXT,  -- hash del IP para detectar abuso, no el IP real
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_captures_email ON email_captures (email);
CREATE INDEX idx_captures_created ON email_captures (created_at DESC);

-- 5. LEAD_EVENTS (NUEVO — tracking de actividad del lead)
-- Cada interacción se registra como evento
CREATE TABLE IF NOT EXISTS lead_events (
    id          BIGSERIAL PRIMARY KEY,
    lead_id     BIGINT REFERENCES leads(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,  -- diagnostic_run | message_sent | email_opened | whatsapp_clicked | reply_sent | status_changed
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_events_lead ON lead_events (lead_id, created_at DESC);
CREATE INDEX idx_events_type ON lead_events (event_type);

-- 6. FUNCIÓN HELPER: auto-update de updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- 7. FUNCIÓN: upsert de lead (crea o actualiza si el email ya existe)
CREATE OR REPLACE FUNCTION upsert_lead(
    p_email TEXT,
    p_name TEXT DEFAULT NULL,
    p_source TEXT DEFAULT 'contact_form',
    p_phone TEXT DEFAULT NULL,
    p_company TEXT DEFAULT NULL
) RETURNS BIGINT AS $$
DECLARE
    v_id BIGINT;
BEGIN
    INSERT INTO leads (email, name, source, phone, company)
    VALUES (p_email, p_name, p_source, p_phone, p_company)
    ON CONFLICT (email) DO UPDATE SET
        name = COALESCE(EXCLUDED.name, leads.name),
        phone = COALESCE(EXCLUDED.phone, leads.phone),
        company = COALESCE(EXCLUDED.company, leads.company),
        updated_at = now()
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

-- ═══════════════════════════════════════════════════════════
-- NOTA: Las RLS (Row Level Security) policies de Supabase
-- no se activan aquí porque el backend usa service_role key
-- que bypasea RLS. Si en el futuro se agrega acceso directo
-- desde el frontend, hay que configurar RLS.
-- ═══════════════════════════════════════════════════════════
