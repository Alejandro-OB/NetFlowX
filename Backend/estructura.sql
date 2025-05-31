--
-- PostgreSQL database dump
--

-- Dumped from database version 16.9 (Ubuntu 16.9-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.9 (Ubuntu 16.9-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: clientes_activos; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.clientes_activos (
    id integer NOT NULL,
    host_cliente character varying(255) NOT NULL,
    servidor_asignado character varying(255),
    ip_destino character varying(15),
    puerto integer,
    video_solicitado character varying(255),
    timestamp_inicio timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    estado character varying(50) DEFAULT 'activo'::character varying,
    hora_asignacion timestamp without time zone
);


ALTER TABLE public.clientes_activos OWNER TO geant_user;

--
-- Name: clientes_activos_id_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.clientes_activos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.clientes_activos_id_seq OWNER TO geant_user;

--
-- Name: clientes_activos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.clientes_activos_id_seq OWNED BY public.clientes_activos.id;


--
-- Name: configuracion; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.configuracion (
    id_configuracion integer NOT NULL,
    algoritmo_balanceo character varying,
    algoritmo_enrutamiento character varying,
    fecha_activacion timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT configuracion_algoritmo_balanceo_check CHECK (((algoritmo_balanceo)::text = ANY ((ARRAY['round_robin'::character varying, 'weighted_round_robin'::character varying])::text[]))),
    CONSTRAINT configuracion_algoritmo_enrutamiento_check CHECK (((algoritmo_enrutamiento)::text = ANY ((ARRAY['shortest_path'::character varying, 'dijkstra'::character varying])::text[])))
);


ALTER TABLE public.configuracion OWNER TO geant_user;

--
-- Name: configuracion_id_configuracion_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.configuracion_id_configuracion_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.configuracion_id_configuracion_seq OWNER TO geant_user;

--
-- Name: configuracion_id_configuracion_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.configuracion_id_configuracion_seq OWNED BY public.configuracion.id_configuracion;


--
-- Name: enlaces; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.enlaces (
    id_enlace integer NOT NULL,
    id_origen integer,
    id_destino integer,
    ancho_banda integer
);


ALTER TABLE public.enlaces OWNER TO geant_user;

--
-- Name: enlaces_id_enlace_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.enlaces_id_enlace_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.enlaces_id_enlace_seq OWNER TO geant_user;

--
-- Name: enlaces_id_enlace_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.enlaces_id_enlace_seq OWNED BY public.enlaces.id_enlace;


--
-- Name: estadisticas; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.estadisticas (
    id_estadistica integer NOT NULL,
    id_host integer,
    tipo character varying,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT estadisticas_tipo_check CHECK (((tipo)::text = ANY ((ARRAY['video_request'::character varying, 'switching'::character varying])::text[])))
);


ALTER TABLE public.estadisticas OWNER TO geant_user;

--
-- Name: estadisticas_id_estadistica_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.estadisticas_id_estadistica_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.estadisticas_id_estadistica_seq OWNER TO geant_user;

--
-- Name: estadisticas_id_estadistica_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.estadisticas_id_estadistica_seq OWNED BY public.estadisticas.id_estadistica;


--
-- Name: host_locations; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.host_locations (
    host_mac character varying(17) NOT NULL,
    dpid integer NOT NULL,
    port integer NOT NULL,
    last_seen timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    ip character varying(15)
);


ALTER TABLE public.host_locations OWNER TO geant_user;

--
-- Name: hosts; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.hosts (
    id_host integer NOT NULL,
    nombre character varying,
    switch_asociado integer,
    es_servidor boolean DEFAULT false,
    activo boolean DEFAULT true,
    ipv4 character varying(15),
    mac character varying(17),
    es_cliente boolean DEFAULT false
);


ALTER TABLE public.hosts OWNER TO geant_user;

--
-- Name: hosts_id_host_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.hosts_id_host_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.hosts_id_host_seq OWNER TO geant_user;

--
-- Name: hosts_id_host_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.hosts_id_host_seq OWNED BY public.hosts.id_host;


--
-- Name: logs; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.logs (
    id integer NOT NULL,
    dpid integer NOT NULL,
    rule_id integer NOT NULL,
    priority integer,
    eth_type character varying(10),
    ip_proto character varying(10),
    ipv4_src character varying(15),
    ipv4_dst character varying(15),
    tcp_src integer,
    tcp_dst integer,
    in_port integer,
    actions text,
    fecha timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    action character varying(20)
);


ALTER TABLE public.logs OWNER TO geant_user;

--
-- Name: logs_id_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.logs_id_seq OWNER TO geant_user;

--
-- Name: logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.logs_id_seq OWNED BY public.logs.id;


--
-- Name: pesos_servidores; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.pesos_servidores (
    id_host integer NOT NULL,
    peso integer
);


ALTER TABLE public.pesos_servidores OWNER TO geant_user;

--
-- Name: puertos; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.puertos (
    id integer NOT NULL,
    nodo_origen character varying NOT NULL,
    nodo_destino character varying NOT NULL,
    puerto_origen integer NOT NULL,
    puerto_destino integer
);


ALTER TABLE public.puertos OWNER TO geant_user;

--
-- Name: puertos_id_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.puertos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.puertos_id_seq OWNER TO geant_user;

--
-- Name: puertos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.puertos_id_seq OWNED BY public.puertos.id;


--
-- Name: reglas; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.reglas (
    dpid integer NOT NULL,
    rule_id integer NOT NULL,
    priority integer DEFAULT 1,
    eth_type integer NOT NULL,
    ip_proto integer,
    ipv4_src text,
    ipv4_dst text,
    tcp_src integer,
    tcp_dst integer,
    in_port integer,
    actions text NOT NULL,
    id integer NOT NULL,
    CONSTRAINT reglas_actions_check CHECK ((actions <> ''::text)),
    CONSTRAINT reglas_eth_type_check CHECK ((eth_type > 0)),
    CONSTRAINT reglas_in_port_check CHECK (((in_port IS NULL) OR (in_port > 0))),
    CONSTRAINT reglas_ip_proto_check CHECK (((ip_proto IS NULL) OR (ip_proto >= 0))),
    CONSTRAINT reglas_priority_check CHECK ((priority > 0)),
    CONSTRAINT reglas_rule_id_check CHECK ((rule_id > 0)),
    CONSTRAINT reglas_tcp_dst_check CHECK (((tcp_dst IS NULL) OR (tcp_dst > 0))),
    CONSTRAINT reglas_tcp_src_check CHECK (((tcp_src IS NULL) OR (tcp_src > 0)))
);


ALTER TABLE public.reglas OWNER TO geant_user;

--
-- Name: reglas_id_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.reglas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reglas_id_seq OWNER TO geant_user;

--
-- Name: reglas_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.reglas_id_seq OWNED BY public.reglas.id;


--
-- Name: rutas; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.rutas (
    id integer NOT NULL,
    src_ip character varying(15) NOT NULL,
    dst_ip character varying(15) NOT NULL,
    ruta jsonb NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now()
);


ALTER TABLE public.rutas OWNER TO geant_user;

--
-- Name: rutas_id_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.rutas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rutas_id_seq OWNER TO geant_user;

--
-- Name: rutas_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.rutas_id_seq OWNED BY public.rutas.id;


--
-- Name: servidores_vlc_activos; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.servidores_vlc_activos (
    id integer NOT NULL,
    host_name character varying(255) NOT NULL,
    video_path character varying(255),
    status character varying(50) DEFAULT 'activo'::character varying NOT NULL,
    process_pid integer,
    ip_destino character varying(15) NOT NULL,
    puerto integer NOT NULL,
    last_updated timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    server_weight integer DEFAULT 1
);


ALTER TABLE public.servidores_vlc_activos OWNER TO geant_user;

--
-- Name: servidores_vlc_activos_id_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.servidores_vlc_activos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.servidores_vlc_activos_id_seq OWNER TO geant_user;

--
-- Name: servidores_vlc_activos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.servidores_vlc_activos_id_seq OWNED BY public.servidores_vlc_activos.id;


--
-- Name: switches; Type: TABLE; Schema: public; Owner: geant_user
--

CREATE TABLE public.switches (
    id_switch integer NOT NULL,
    nombre character varying,
    longitud double precision,
    latitud double precision,
    switch_label text,
    status character varying(50) DEFAULT 'desconectado'::character varying,
    last_updated timestamp with time zone DEFAULT now()
);


ALTER TABLE public.switches OWNER TO geant_user;

--
-- Name: switches_id_switch_seq; Type: SEQUENCE; Schema: public; Owner: geant_user
--

CREATE SEQUENCE public.switches_id_switch_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.switches_id_switch_seq OWNER TO geant_user;

--
-- Name: switches_id_switch_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: geant_user
--

ALTER SEQUENCE public.switches_id_switch_seq OWNED BY public.switches.id_switch;


--
-- Name: clientes_activos id; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.clientes_activos ALTER COLUMN id SET DEFAULT nextval('public.clientes_activos_id_seq'::regclass);


--
-- Name: configuracion id_configuracion; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.configuracion ALTER COLUMN id_configuracion SET DEFAULT nextval('public.configuracion_id_configuracion_seq'::regclass);


--
-- Name: enlaces id_enlace; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.enlaces ALTER COLUMN id_enlace SET DEFAULT nextval('public.enlaces_id_enlace_seq'::regclass);


--
-- Name: estadisticas id_estadistica; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.estadisticas ALTER COLUMN id_estadistica SET DEFAULT nextval('public.estadisticas_id_estadistica_seq'::regclass);


--
-- Name: hosts id_host; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.hosts ALTER COLUMN id_host SET DEFAULT nextval('public.hosts_id_host_seq'::regclass);


--
-- Name: logs id; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.logs ALTER COLUMN id SET DEFAULT nextval('public.logs_id_seq'::regclass);


--
-- Name: puertos id; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.puertos ALTER COLUMN id SET DEFAULT nextval('public.puertos_id_seq'::regclass);


--
-- Name: reglas id; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.reglas ALTER COLUMN id SET DEFAULT nextval('public.reglas_id_seq'::regclass);


--
-- Name: rutas id; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.rutas ALTER COLUMN id SET DEFAULT nextval('public.rutas_id_seq'::regclass);


--
-- Name: servidores_vlc_activos id; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.servidores_vlc_activos ALTER COLUMN id SET DEFAULT nextval('public.servidores_vlc_activos_id_seq'::regclass);


--
-- Name: switches id_switch; Type: DEFAULT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.switches ALTER COLUMN id_switch SET DEFAULT nextval('public.switches_id_switch_seq'::regclass);


--
-- Name: clientes_activos clientes_activos_host_cliente_key; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.clientes_activos
    ADD CONSTRAINT clientes_activos_host_cliente_key UNIQUE (host_cliente);


--
-- Name: clientes_activos clientes_activos_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.clientes_activos
    ADD CONSTRAINT clientes_activos_pkey PRIMARY KEY (id);


--
-- Name: configuracion configuracion_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.configuracion
    ADD CONSTRAINT configuracion_pkey PRIMARY KEY (id_configuracion);


--
-- Name: enlaces enlaces_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.enlaces
    ADD CONSTRAINT enlaces_pkey PRIMARY KEY (id_enlace);


--
-- Name: estadisticas estadisticas_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.estadisticas
    ADD CONSTRAINT estadisticas_pkey PRIMARY KEY (id_estadistica);


--
-- Name: host_locations host_locations_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.host_locations
    ADD CONSTRAINT host_locations_pkey PRIMARY KEY (host_mac);


--
-- Name: hosts hosts_nombre_key; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.hosts
    ADD CONSTRAINT hosts_nombre_key UNIQUE (nombre);


--
-- Name: hosts hosts_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.hosts
    ADD CONSTRAINT hosts_pkey PRIMARY KEY (id_host);


--
-- Name: logs logs_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.logs
    ADD CONSTRAINT logs_pkey PRIMARY KEY (id);


--
-- Name: pesos_servidores pesos_servidores_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.pesos_servidores
    ADD CONSTRAINT pesos_servidores_pkey PRIMARY KEY (id_host);


--
-- Name: puertos puertos_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.puertos
    ADD CONSTRAINT puertos_pkey PRIMARY KEY (id);


--
-- Name: reglas reglas_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.reglas
    ADD CONSTRAINT reglas_pkey PRIMARY KEY (id);


--
-- Name: reglas reglas_rule_id_key; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.reglas
    ADD CONSTRAINT reglas_rule_id_key UNIQUE (rule_id);


--
-- Name: rutas rutas_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.rutas
    ADD CONSTRAINT rutas_pkey PRIMARY KEY (id);


--
-- Name: servidores_vlc_activos servidores_vlc_activos_host_name_key; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.servidores_vlc_activos
    ADD CONSTRAINT servidores_vlc_activos_host_name_key UNIQUE (host_name);


--
-- Name: servidores_vlc_activos servidores_vlc_activos_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.servidores_vlc_activos
    ADD CONSTRAINT servidores_vlc_activos_pkey PRIMARY KEY (id);


--
-- Name: switches switches_nombre_key; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.switches
    ADD CONSTRAINT switches_nombre_key UNIQUE (nombre);


--
-- Name: switches switches_pkey; Type: CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.switches
    ADD CONSTRAINT switches_pkey PRIMARY KEY (id_switch);


--
-- Name: idx_clientes_activos_host_cliente; Type: INDEX; Schema: public; Owner: geant_user
--

CREATE INDEX idx_clientes_activos_host_cliente ON public.clientes_activos USING btree (host_cliente);


--
-- Name: idx_host_locations_dpid; Type: INDEX; Schema: public; Owner: geant_user
--

CREATE INDEX idx_host_locations_dpid ON public.host_locations USING btree (dpid);


--
-- Name: idx_servidores_vlc_activos_host_name; Type: INDEX; Schema: public; Owner: geant_user
--

CREATE UNIQUE INDEX idx_servidores_vlc_activos_host_name ON public.servidores_vlc_activos USING btree (host_name);


--
-- Name: enlaces enlaces_id_destino_fkey; Type: FK CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.enlaces
    ADD CONSTRAINT enlaces_id_destino_fkey FOREIGN KEY (id_destino) REFERENCES public.switches(id_switch);


--
-- Name: enlaces enlaces_id_origen_fkey; Type: FK CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.enlaces
    ADD CONSTRAINT enlaces_id_origen_fkey FOREIGN KEY (id_origen) REFERENCES public.switches(id_switch);


--
-- Name: estadisticas estadisticas_id_host_fkey; Type: FK CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.estadisticas
    ADD CONSTRAINT estadisticas_id_host_fkey FOREIGN KEY (id_host) REFERENCES public.hosts(id_host);


--
-- Name: host_locations fk_dpid; Type: FK CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.host_locations
    ADD CONSTRAINT fk_dpid FOREIGN KEY (dpid) REFERENCES public.switches(id_switch) ON DELETE CASCADE;


--
-- Name: hosts hosts_switch_asociado_fkey; Type: FK CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.hosts
    ADD CONSTRAINT hosts_switch_asociado_fkey FOREIGN KEY (switch_asociado) REFERENCES public.switches(id_switch);


--
-- Name: pesos_servidores pesos_servidores_id_host_fkey; Type: FK CONSTRAINT; Schema: public; Owner: geant_user
--

ALTER TABLE ONLY public.pesos_servidores
    ADD CONSTRAINT pesos_servidores_id_host_fkey FOREIGN KEY (id_host) REFERENCES public.hosts(id_host);


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

GRANT ALL ON SCHEMA public TO geant_user;


--
-- PostgreSQL database dump complete
--

