-- ============================================================================
--  BANCO DE INTELIGÊNCIA DE PREÇOS
--  Modelo relacional normalizado (3FN) — MySQL 8+ / InnoDB
--
--  Modela a saída do pipeline (resultados_csv/*.csv), cujas colunas são:
--      produto ; loja ; preco ; em_oferta ; data
--  Cada linha é uma coleta de preço de um produto, numa loja, numa data.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS price_intelligence
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE price_intelligence;

-- ----------------------------------------------------------------------------
--  DIMENSÃO: PRODUTO
-- ----------------------------------------------------------------------------
CREATE TABLE dim_produto (
  pk_produto    INT           NOT NULL AUTO_INCREMENT,
  nome_produto  VARCHAR(150)  NOT NULL,
  ean           CHAR(13)      NULL,        -- validado por validar_ean() no pipeline
  PRIMARY KEY (pk_produto),
  UNIQUE KEY uq_produto_nome (nome_produto)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
--  DIMENSÃO: LOJA  (própria ou concorrente)
-- ----------------------------------------------------------------------------
CREATE TABLE dim_loja (
  pk_loja    INT                              NOT NULL AUTO_INCREMENT,
  nome_loja  VARCHAR(80)                      NOT NULL,
  tipo       ENUM('propria','concorrente')    NOT NULL DEFAULT 'concorrente',
  PRIMARY KEY (pk_loja),
  UNIQUE KEY uq_loja_nome (nome_loja)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
--  FATO: COLETA DE PREÇO
--  Grão: produto × loja × data. Uma coleta por dia por loja/produto.
-- ----------------------------------------------------------------------------
CREATE TABLE fato_preco (
  pk_preco     BIGINT         NOT NULL AUTO_INCREMENT,
  fk_produto   INT            NOT NULL,
  fk_loja      INT            NOT NULL,
  data_coleta  DATE           NOT NULL,
  preco        DECIMAL(12,2)  NOT NULL,
  em_oferta    BOOLEAN        NOT NULL DEFAULT 0,   -- 'Sim'/'Não' no CSV
  PRIMARY KEY (pk_preco),
  UNIQUE KEY uq_coleta (fk_produto, fk_loja, data_coleta),
  CONSTRAINT fk_preco_produto FOREIGN KEY (fk_produto) REFERENCES dim_produto (pk_produto),
  CONSTRAINT fk_preco_loja    FOREIGN KEY (fk_loja)    REFERENCES dim_loja (pk_loja)
) ENGINE=InnoDB;

CREATE INDEX ix_preco_data    ON fato_preco (data_coleta);
CREATE INDEX ix_preco_produto ON fato_preco (fk_produto);

-- ----------------------------------------------------------------------------
--  VIEW: comparativo de preços por produto/data (loja mais barata)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_comparativo_precos AS
SELECT
  p.nome_produto,
  f.data_coleta,
  l.nome_loja,
  l.tipo,
  f.preco,
  f.em_oferta,
  MIN(f.preco) OVER (PARTITION BY f.fk_produto, f.data_coleta) AS menor_preco_do_dia
FROM fato_preco f
JOIN dim_produto p ON p.pk_produto = f.fk_produto
JOIN dim_loja    l ON l.pk_loja    = f.fk_loja;
