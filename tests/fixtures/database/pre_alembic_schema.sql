-- Schema of a ValScores PostgreSQL database created by SQLAlchemy create_all()
-- before Alembic (overhaul tickets 01-03), captured with pg_dump --schema-only.
-- Tests load it to stand in for an existing installation that must be baselined.
-- Do not edit: it is a historical snapshot, not the current schema.

CREATE TABLE public.games (
    id integer NOT NULL,
    match_id integer NOT NULL,
    vlr_game_id character varying NOT NULL,
    map_number integer,
    map_name character varying NOT NULL,
    team1_round_score integer,
    team2_round_score integer
);

CREATE SEQUENCE public.games_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.games_id_seq OWNED BY public.games.id;

CREATE TABLE public.matches (
    id integer NOT NULL,
    vlr_match_id character varying NOT NULL,
    team1_name character varying NOT NULL,
    team2_name character varying NOT NULL,
    team1_round_score character varying,
    team2_round_score character varying,
    start_time timestamp with time zone,
    legacy_start_time character varying,
    status character varying,
    team1_series_score integer,
    team2_series_score integer,
    map_vetoes_raw character varying
);

CREATE SEQUENCE public.matches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.matches_id_seq OWNED BY public.matches.id;

CREATE TABLE public.player_stats (
    id integer NOT NULL,
    game_id integer NOT NULL,
    player_name character varying NOT NULL,
    team_name character varying NOT NULL,
    role character varying,
    acs integer,
    kd_ratio double precision,
    adr integer,
    kills integer,
    deaths integer,
    assists integer,
    plus_minus character varying,
    kast character varying,
    first_kills integer,
    first_deaths integer
);

CREATE SEQUENCE public.player_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.player_stats_id_seq OWNED BY public.player_stats.id;

ALTER TABLE ONLY public.games ALTER COLUMN id SET DEFAULT nextval('public.games_id_seq'::regclass);

ALTER TABLE ONLY public.matches ALTER COLUMN id SET DEFAULT nextval('public.matches_id_seq'::regclass);

ALTER TABLE ONLY public.player_stats ALTER COLUMN id SET DEFAULT nextval('public.player_stats_id_seq'::regclass);

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.matches
    ADD CONSTRAINT matches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.player_stats
    ADD CONSTRAINT player_stats_pkey PRIMARY KEY (id);

CREATE INDEX ix_games_vlr_game_id ON public.games USING btree (vlr_game_id);

CREATE UNIQUE INDEX ix_matches_vlr_match_id ON public.matches USING btree (vlr_match_id);

CREATE UNIQUE INDEX uq_games_match_id_vlr_game_id ON public.games USING btree (match_id, vlr_game_id);

CREATE UNIQUE INDEX uq_player_stats_game_player_identity ON public.player_stats USING btree (game_id, team_name, player_name);

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_match_id_fkey FOREIGN KEY (match_id) REFERENCES public.matches(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.player_stats
    ADD CONSTRAINT player_stats_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;
