
import io
import math
import os
import sys
import unicodedata
from pathlib import Path
from datetime import date, timedelta

try:
    import numpy as np
    import pandas as pd
    import streamlit as st
except ModuleNotFoundError as e:
    pacote = getattr(e, "name", "dependência")
    print("\nEste arquivo é um aplicativo web feito em Streamlit.")
    print("Para desenvolvimento local, instale as dependências com:")
    print("python -m pip install -r requirements.txt\n")
    print("Para o cliente final não precisar instalar Python, hospede o app na web e envie apenas o link de acesso.")
    print(f"Dependência ausente no ambiente atual: {pacote}\n")
    sys.exit(1)


# ============================================================
# APP DE GESTÃO INTELIGENTE DE ESTOQUE PARA FARMÁCIAS
# ============================================================
# Uso recomendado:
# - Cliente final: acessar por link do app hospedado na web.
# - Desenvolvimento local: python -m streamlit run app.py
#
# Ideia principal:
# - O usuário fornece um CSV inicial com o estoque atual.
# - O app lê o CSV, padroniza as colunas e cria sua base interna.
# - Depois disso, o app passa a registrar vendas, perdas, rupturas,
#   analisar Curva ABC, validade, recompra e recomendações.
# ============================================================
def exigir_execucao_streamlit():
    """Impede execução em modo Python puro, que quebra o ciclo do Streamlit."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return

    if get_script_run_ctx() is None:
        arquivo = Path(__file__).resolve()
        print("\nEste arquivo é um aplicativo Streamlit e não deve ser executado com python -u.")
        print("Use o comando abaixo no PowerShell:\n")
        print(f'python -m streamlit run "{arquivo}"')
        print()
        sys.exit(0)


def remover_colunas_duplicadas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    return df.loc[:, ~pd.Index(df.columns).duplicated()].copy()


def colunas_unicas(colunas: list) -> list:
    unicas = []
    vistas = set()
    for col in colunas:
        if col not in vistas:
            unicas.append(col)
            vistas.add(col)
    return unicas


def selecionar_colunas(df: pd.DataFrame, colunas: list) -> pd.DataFrame:
    df = remover_colunas_duplicadas(df)
    colunas = colunas_unicas([col for col in colunas if col in df.columns])
    return df.loc[:, colunas].copy()


def dataframe_seguro(df: pd.DataFrame, colunas: list | None = None) -> pd.DataFrame:
    df = remover_colunas_duplicadas(df)
    if colunas is not None:
        df = selecionar_colunas(df, colunas)
    return df


def mostrar_dataframe(df: pd.DataFrame, colunas: list | None = None, **kwargs):
    return st.dataframe(dataframe_seguro(df, colunas), **kwargs)


def csv_download(df: pd.DataFrame) -> str:
    return dataframe_seguro(df).to_csv(index=False, encoding="utf-8-sig")


exigir_execucao_streamlit()

st.set_page_config(
    page_title="Gestão Inteligente de Estoque - Farmácia",
    page_icon="💊",
    layout="wide",
)

DATA_DIR = Path(os.getenv("DATA_FARMACIA_DIR", Path(__file__).resolve().parent / "data_farmacia"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRODUTOS_FILE = DATA_DIR / "produtos.csv"
VENDAS_FILE = DATA_DIR / "vendas.csv"
PERDAS_FILE = DATA_DIR / "perdas.csv"
RUPTURAS_FILE = DATA_DIR / "rupturas.csv"

COL_PRODUTOS = [
    "codigo",
    "nome",
    "categoria",
    "fornecedor",
    "custo",
    "preco_venda",
    "estoque_atual",
    "estoque_minimo",
    "estoque_maximo",
    "lote",
    "validade",
    "localizacao",
    "produto_estrategico",
    "ativo",
]

COL_VENDAS = [
    "data",
    "codigo",
    "quantidade",
    "preco_venda",
    "custo_unitario",
    "desconto_unitario",
    "atendente",
]

COL_PERDAS = [
    "data",
    "codigo",
    "quantidade",
    "motivo",
    "valor_estimado",
    "observacao",
]

COL_RUPTURAS = [
    "data",
    "codigo",
    "quantidade_solicitada",
    "observacao",
]


# ============================================================
# UTILITÁRIOS
# ============================================================

def moeda(valor: float) -> str:
    try:
        valor = float(valor)
    except Exception:
        valor = 0.0
    txt = f"R$ {valor:,.2f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def porcentagem(valor: float) -> str:
    try:
        return f"{float(valor):.1%}".replace(".", ",")
    except Exception:
        return "0,0%"


def normalizar_texto(txt: str) -> str:
    txt = str(txt).strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = txt.replace("ç", "c")
    for ch in [" ", "-", ".", "/", "\\", "(", ")", "[", "]"]:
        txt = txt.replace(ch, "_")
    while "__" in txt:
        txt = txt.replace("__", "_")
    return txt.strip("_")


def numero_brasileiro_para_float(valor):
    if pd.isna(valor):
        return 0.0
    if isinstance(valor, (int, float, np.number)):
        return float(valor)
    txt = str(valor).strip()
    if txt == "":
        return 0.0
    txt = txt.replace("R$", "").replace(" ", "")
    # Caso brasileiro: 1.234,56
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return 0.0


def sim_nao_para_bool(valor, padrao=False):
    if pd.isna(valor):
        return padrao
    txt = str(valor).strip().lower()
    return txt in ["sim", "s", "true", "1", "yes", "y", "ativo", "estrategico"]


def salvar_csv(df: pd.DataFrame, caminho: Path):
    df = remover_colunas_duplicadas(df)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho, index=False, encoding="utf-8-sig")


def carregar_csv(caminho: Path, colunas: list) -> pd.DataFrame:
    if not caminho.exists():
        return pd.DataFrame(columns=colunas)
    try:
        df = pd.read_csv(caminho, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(caminho, encoding="latin1")

    df = remover_colunas_duplicadas(df)
    for col in colunas:
        if col not in df.columns:
            df[col] = np.nan
    return df.loc[:, colunas].copy()


def normalizar_produtos(df: pd.DataFrame) -> pd.DataFrame:
    df = remover_colunas_duplicadas(df.copy())
    for col in COL_PRODUTOS:
        if col not in df.columns:
            df[col] = np.nan

    df = df[COL_PRODUTOS]
    df["codigo"] = df["codigo"].fillna("").astype(str).str.strip()
    df["nome"] = df["nome"].fillna("").astype(str).str.strip()
    df["categoria"] = df["categoria"].fillna("Sem categoria").astype(str).str.strip()
    df["fornecedor"] = df["fornecedor"].fillna("Sem fornecedor").astype(str).str.strip()

    for col in ["custo", "preco_venda", "estoque_atual", "estoque_minimo", "estoque_maximo"]:
        df[col] = df[col].apply(numero_brasileiro_para_float)

    df["lote"] = df["lote"].fillna("").astype(str).str.strip()
    df["validade"] = pd.to_datetime(df["validade"], errors="coerce", dayfirst=True).dt.date.astype(str)
    df.loc[df["validade"].isin(["NaT", "nan", "None"]), "validade"] = ""
    df["localizacao"] = df["localizacao"].fillna("").astype(str).str.strip()
    df["produto_estrategico"] = df["produto_estrategico"].apply(lambda x: sim_nao_para_bool(x, False))
    df["ativo"] = df["ativo"].apply(lambda x: sim_nao_para_bool(x, True))

    # Gerar código se vier vazio.
    codigos_vazios = df["codigo"].eq("") | df["codigo"].eq("nan")
    if codigos_vazios.any():
        for i, idx in enumerate(df[codigos_vazios].index, start=1):
            df.loc[idx, "codigo"] = f"PROD{i:05d}"

    # Remover linhas totalmente vazias.
    df = df[df["nome"].astype(str).str.strip() != ""].copy()
    return df.reset_index(drop=True)


def normalizar_vendas(df: pd.DataFrame) -> pd.DataFrame:
    df = remover_colunas_duplicadas(df.copy())
    for col in COL_VENDAS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[COL_VENDAS]
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df["codigo"] = df["codigo"].fillna("").astype(str).str.strip()
    for col in ["quantidade", "preco_venda", "custo_unitario", "desconto_unitario"]:
        df[col] = df[col].apply(numero_brasileiro_para_float)
    df["atendente"] = df["atendente"].fillna("").astype(str)
    return df.dropna(subset=["data"]).reset_index(drop=True)


def normalizar_perdas(df: pd.DataFrame) -> pd.DataFrame:
    df = remover_colunas_duplicadas(df.copy())
    for col in COL_PERDAS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[COL_PERDAS]
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df["codigo"] = df["codigo"].fillna("").astype(str).str.strip()
    df["quantidade"] = df["quantidade"].apply(numero_brasileiro_para_float)
    df["valor_estimado"] = df["valor_estimado"].apply(numero_brasileiro_para_float)
    df["motivo"] = df["motivo"].fillna("").astype(str)
    df["observacao"] = df["observacao"].fillna("").astype(str)
    return df.dropna(subset=["data"]).reset_index(drop=True)


def normalizar_rupturas(df: pd.DataFrame) -> pd.DataFrame:
    df = remover_colunas_duplicadas(df.copy())
    for col in COL_RUPTURAS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[COL_RUPTURAS]
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df["codigo"] = df["codigo"].fillna("").astype(str).str.strip()
    df["quantidade_solicitada"] = df["quantidade_solicitada"].apply(numero_brasileiro_para_float)
    df["observacao"] = df["observacao"].fillna("").astype(str)
    return df.dropna(subset=["data"]).reset_index(drop=True)


def ler_csv_upload(uploaded_file) -> pd.DataFrame:
    conteudo = uploaded_file.getvalue()
    erros = []
    for enc in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
        try:
            df = pd.read_csv(io.BytesIO(conteudo), sep=None, engine="python", encoding=enc)
            return remover_colunas_duplicadas(df)
        except Exception as e:
            erros.append(str(e))
    raise ValueError("Não foi possível ler o CSV. Verifique separador, codificação e estrutura.")


def ler_planilha_upload(uploaded_file) -> pd.DataFrame:
    nome = uploaded_file.name.lower()
    conteudo = uploaded_file.getvalue()

    if nome.endswith(".csv"):
        return ler_csv_upload(uploaded_file)

    if nome.endswith((".xlsx", ".xls")):
        try:
            df = pd.read_excel(io.BytesIO(conteudo))
            return remover_colunas_duplicadas(df)
        except ImportError:
            raise ValueError("Para ler Excel, instale o pacote openpyxl com: python -m pip install openpyxl")
        except Exception as e:
            raise ValueError(f"Não foi possível ler a planilha Excel: {e}")

    raise ValueError("Formato não suportado. Envie arquivo CSV, XLSX ou XLS.")


# ============================================================
# IMPORTAÇÃO DO CSV INICIAL DE ESTOQUE
# ============================================================

SINONIMOS_COLUNAS = {
    "codigo": [
        "codigo", "cod", "sku", "id", "ean", "gtin", "codigo_barras",
        "cod_barras", "barcode", "referencia"
    ],
    "nome": [
        "nome", "produto", "descricao", "descrição", "item",
        "nome_produto", "produto_descricao"
    ],
    "categoria": [
        "categoria", "grupo", "familia", "família", "departamento", "classe", "linha"
    ],
    "fornecedor": [
        "fornecedor", "distribuidor", "laboratorio", "laboratório", "marca", "fabricante"
    ],
    "custo": [
        "custo", "preco_custo", "preço_custo", "custo_unitario",
        "custo_unitário", "valor_custo", "ultimo_custo", "último_custo"
    ],
    "preco_venda": [
        "preco_venda", "preço_venda", "preco", "preço", "valor_venda",
        "venda", "pmc", "preco_atual", "preço_atual"
    ],
    "estoque_atual": [
        "estoque", "estoque_atual", "quantidade", "qtd", "saldo",
        "saldo_estoque", "qtde", "qtd_estoque"
    ],
    "estoque_minimo": [
        "estoque_minimo", "estoque_mínimo", "minimo", "mínimo",
        "estoque_min", "min"
    ],
    "estoque_maximo": [
        "estoque_maximo", "estoque_máximo", "maximo", "máximo",
        "estoque_max", "max"
    ],
    "lote": [
        "lote", "numero_lote", "n_lote", "num_lote"
    ],
    "validade": [
        "validade", "vencimento", "data_validade", "data_vencimento",
        "dt_validade", "dt_vencimento"
    ],
    "localizacao": [
        "localizacao", "localização", "prateleira", "setor", "gondola",
        "gôndola", "endereco", "endereço"
    ],
    "produto_estrategico": [
        "produto_estrategico", "estrategico", "estratégico", "chave",
        "produto_chave"
    ],
    "ativo": [
        "ativo", "status", "situacao", "situação"
    ],
}


def detectar_mapeamento_colunas(df: pd.DataFrame) -> dict:
    colunas_normalizadas = {normalizar_texto(c): c for c in df.columns}
    mapa = {}

    for destino, sinonimos in SINONIMOS_COLUNAS.items():
        mapa[destino] = ""
        for s in sinonimos:
            s_norm = normalizar_texto(s)
            if s_norm in colunas_normalizadas:
                mapa[destino] = colunas_normalizadas[s_norm]
                break
    return mapa


def padronizar_estoque_inicial(df_original: pd.DataFrame, mapa: dict) -> pd.DataFrame:
    linhas = []
    for _, row in df_original.iterrows():
        item = {}
        for destino in COL_PRODUTOS:
            origem = mapa.get(destino, "")
            if origem and origem in df_original.columns:
                item[destino] = row[origem]
            else:
                item[destino] = np.nan

        # Defaults importantes
        if pd.isna(item.get("categoria")):
            item["categoria"] = "Sem categoria"
        if pd.isna(item.get("fornecedor")):
            item["fornecedor"] = "Sem fornecedor"
        if pd.isna(item.get("estoque_minimo")):
            item["estoque_minimo"] = 0
        if pd.isna(item.get("estoque_maximo")):
            item["estoque_maximo"] = 0
        if pd.isna(item.get("produto_estrategico")):
            item["produto_estrategico"] = False
        if pd.isna(item.get("ativo")):
            item["ativo"] = True

        linhas.append(item)

    produtos = pd.DataFrame(linhas, columns=COL_PRODUTOS)
    return normalizar_produtos(produtos)


def sistema_configurado() -> bool:
    return PRODUTOS_FILE.exists() and carregar_csv(PRODUTOS_FILE, COL_PRODUTOS).shape[0] > 0


def inicializar_arquivos_vazios():
    if not VENDAS_FILE.exists():
        salvar_csv(pd.DataFrame(columns=COL_VENDAS), VENDAS_FILE)
    if not PERDAS_FILE.exists():
        salvar_csv(pd.DataFrame(columns=COL_PERDAS), PERDAS_FILE)
    if not RUPTURAS_FILE.exists():
        salvar_csv(pd.DataFrame(columns=COL_RUPTURAS), RUPTURAS_FILE)


def tela_configuracao_inicial():
    st.title("💊 Configuração inicial do app de estoque da farmácia")
    st.markdown(
        """
        Envie uma **planilha com o estoque atual** da farmácia.  
        O app fará a configuração interna, padronizando as colunas para usar nos módulos de estoque, vendas, Curva ABC, validade, recompra e recomendações.
        """
    )

    st.info(
        "A planilha pode ter nomes de colunas diferentes. O app tenta reconhecer automaticamente campos como produto, descrição, estoque, quantidade, custo, preço, validade, lote e fornecedor."
    )

    with st.expander("Estrutura recomendada do CSV inicial"):
        st.code(
            "codigo,nome,categoria,fornecedor,custo,preco_venda,estoque_atual,estoque_minimo,estoque_maximo,lote,validade,localizacao\n"
            "1001,Dipirona 500mg,Medicamentos,Distribuidora Alfa,3.20,7.90,60,20,120,L001,2027-12-31,Balcão\n",
            language="csv",
        )

    uploaded = st.file_uploader("Enviar planilha do estoque atual", type=["csv", "xlsx", "xls"])

    if uploaded is None:
        st.warning("Envie a planilha inicial para configurar o sistema.")
        st.stop()

    try:
        df_original = ler_planilha_upload(uploaded)
    except Exception as e:
        st.error(str(e))
        st.stop()

    st.subheader("Prévia da planilha recebida")
    mostrar_dataframe(df_original.head(20), use_container_width=True)

    mapa_detectado = detectar_mapeamento_colunas(df_original)

    st.subheader("Mapeamento das colunas")
    st.caption("Confirme ou ajuste quais colunas da sua planilha correspondem aos campos internos do app.")

    opcoes = [""] + colunas_unicas(list(df_original.columns))
    mapa_final = {}

    campos_obrigatorios = ["nome", "estoque_atual"]
    campos_importantes = ["codigo", "custo", "preco_venda", "validade", "lote"]

    col1, col2, col3 = st.columns(3)
    colunas_layout = [col1, col2, col3]

    for i, destino in enumerate(COL_PRODUTOS):
        coluna = colunas_layout[i % 3]
        default = mapa_detectado.get(destino, "")
        index_default = opcoes.index(default) if default in opcoes else 0

        label = destino
        if destino in campos_obrigatorios:
            label += " *"
        elif destino in campos_importantes:
            label += " recomendado"

        mapa_final[destino] = coluna.selectbox(
            label,
            opcoes,
            index=index_default,
            key=f"map_{destino}",
        )

    if not mapa_final.get("nome"):
        st.error("O campo 'nome' é obrigatório. Selecione a coluna que representa o nome ou descrição do produto.")
        st.stop()

    if not mapa_final.get("estoque_atual"):
        st.error("O campo 'estoque_atual' é obrigatório. Selecione a coluna que representa a quantidade em estoque.")
        st.stop()

    produtos_padronizados = padronizar_estoque_inicial(df_original, mapa_final)

    if produtos_padronizados.empty:
        st.error("A planilha foi lida, mas nenhum produto válido foi identificado. Verifique o mapeamento das colunas.")
        st.stop()

    st.subheader("Prévia da base interna padronizada")
    mostrar_dataframe(produtos_padronizados.head(20), use_container_width=True)

    c1, c2 = st.columns(2)
    c1.metric("Produtos importados", produtos_padronizados.shape[0])
    c2.metric("Valor de estoque estimado", moeda((produtos_padronizados["estoque_atual"] * produtos_padronizados["custo"]).sum()))

    if st.button("✅ Configurar sistema com esta planilha", type="primary"):
        salvar_csv(produtos_padronizados, PRODUTOS_FILE)
        inicializar_arquivos_vazios()
        st.success("Sistema configurado com sucesso. Recarregando o app...")
        st.rerun()


# ============================================================
# CÁLCULOS
# ============================================================

def carregar_bases():
    produtos = normalizar_produtos(carregar_csv(PRODUTOS_FILE, COL_PRODUTOS))
    vendas = normalizar_vendas(carregar_csv(VENDAS_FILE, COL_VENDAS))
    perdas = normalizar_perdas(carregar_csv(PERDAS_FILE, COL_PERDAS))
    rupturas = normalizar_rupturas(carregar_csv(RUPTURAS_FILE, COL_RUPTURAS))
    return produtos, vendas, perdas, rupturas


def filtrar_vendas_periodo(vendas, inicio, fim):
    if vendas.empty:
        return vendas.copy()
    inicio = pd.Timestamp(inicio)
    fim = pd.Timestamp(fim) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return vendas[(vendas["data"] >= inicio) & (vendas["data"] <= fim)].copy()


def calcular_metricas_produtos(produtos, vendas, inicio, fim):
    produtos = produtos.copy()
    vendas_periodo = filtrar_vendas_periodo(vendas, inicio, fim)
    dias_periodo = max(1, (pd.Timestamp(fim) - pd.Timestamp(inicio)).days + 1)

    if vendas_periodo.empty:
        metricas = produtos.copy()
        metricas["quantidade_vendida"] = 0.0
        metricas["faturamento_liquido"] = 0.0
        metricas["custo_total_vendido"] = 0.0
        metricas["margem_total"] = 0.0
    else:
        vendas_periodo["receita_item"] = (
            vendas_periodo["preco_venda"] - vendas_periodo["desconto_unitario"]
        ) * vendas_periodo["quantidade"]
        vendas_periodo["custo_item"] = vendas_periodo["custo_unitario"] * vendas_periodo["quantidade"]
        vendas_periodo["margem_item"] = vendas_periodo["receita_item"] - vendas_periodo["custo_item"]

        resumo = vendas_periodo.groupby("codigo", as_index=False).agg(
            quantidade_vendida=("quantidade", "sum"),
            faturamento_liquido=("receita_item", "sum"),
            custo_total_vendido=("custo_item", "sum"),
            margem_total=("margem_item", "sum"),
        )

        metricas = produtos.merge(resumo, on="codigo", how="left")
        for col in ["quantidade_vendida", "faturamento_liquido", "custo_total_vendido", "margem_total"]:
            metricas[col] = metricas[col].fillna(0.0)

    metricas["margem_percentual"] = np.where(
        metricas["faturamento_liquido"] > 0,
        metricas["margem_total"] / metricas["faturamento_liquido"],
        0,
    )
    metricas["venda_media_diaria"] = metricas["quantidade_vendida"] / dias_periodo
    metricas["valor_estoque"] = metricas["estoque_atual"] * metricas["custo"]
    metricas["lucro_unitario"] = metricas["preco_venda"] - metricas["custo"]
    metricas["dias_cobertura"] = np.where(
        metricas["venda_media_diaria"] > 0,
        metricas["estoque_atual"] / metricas["venda_media_diaria"],
        np.inf,
    )

    validade = pd.to_datetime(metricas["validade"], errors="coerce")
    metricas["dias_para_vencer"] = (validade - pd.Timestamp(date.today())).dt.days

    metricas["status_validade"] = np.select(
        [
            metricas["dias_para_vencer"].isna(),
            metricas["dias_para_vencer"] < 0,
            metricas["dias_para_vencer"] <= 30,
            metricas["dias_para_vencer"] <= 60,
            metricas["dias_para_vencer"] <= 90,
            metricas["dias_para_vencer"] <= 180,
        ],
        [
            "Sem validade",
            "Vencido",
            "Crítico até 30 dias",
            "Atenção até 60 dias",
            "Atenção até 90 dias",
            "Monitorar até 180 dias",
        ],
        default="Ok",
    )

    return metricas


def aplicar_curva_abc(df, coluna_metrica, limite_a=0.80, limite_b=0.95, coluna_saida="classe_abc"):
    base = df.copy()
    base[coluna_metrica] = pd.to_numeric(base[coluna_metrica], errors="coerce").fillna(0)
    total = base[coluna_metrica].sum()

    if total <= 0:
        base[coluna_saida] = "C"
        base[f"participacao_{coluna_metrica}"] = 0.0
        base[f"participacao_acumulada_{coluna_metrica}"] = 0.0
        return base

    base = base.sort_values(coluna_metrica, ascending=False).reset_index(drop=True)
    base[f"participacao_{coluna_metrica}"] = base[coluna_metrica] / total
    base[f"participacao_acumulada_{coluna_metrica}"] = base[f"participacao_{coluna_metrica}"].cumsum()

    base[coluna_saida] = np.select(
        [
            base[f"participacao_acumulada_{coluna_metrica}"] <= limite_a,
            base[f"participacao_acumulada_{coluna_metrica}"] <= limite_b,
        ],
        ["A", "B"],
        default="C",
    )
    return base


def calcular_abc_completo(produtos, vendas, inicio, fim, limite_a=0.80, limite_b=0.95):
    metricas = calcular_metricas_produtos(produtos, vendas, inicio, fim)

    abc_faturamento = aplicar_curva_abc(
        metricas[["codigo", "faturamento_liquido"]],
        "faturamento_liquido",
        limite_a,
        limite_b,
        "abc_faturamento",
    )[["codigo", "abc_faturamento", "participacao_faturamento_liquido", "participacao_acumulada_faturamento_liquido"]]

    abc_margem = aplicar_curva_abc(
        metricas[["codigo", "margem_total"]],
        "margem_total",
        limite_a,
        limite_b,
        "abc_margem",
    )[["codigo", "abc_margem", "participacao_margem_total", "participacao_acumulada_margem_total"]]

    abc_giro = aplicar_curva_abc(
        metricas[["codigo", "quantidade_vendida"]],
        "quantidade_vendida",
        limite_a,
        limite_b,
        "abc_giro",
    )[["codigo", "abc_giro", "participacao_quantidade_vendida", "participacao_acumulada_quantidade_vendida"]]

    resultado = metricas.merge(abc_faturamento, on="codigo", how="left")
    resultado = resultado.merge(abc_margem, on="codigo", how="left")
    resultado = resultado.merge(abc_giro, on="codigo", how="left")

    for col in ["abc_faturamento", "abc_margem", "abc_giro"]:
        resultado[col] = resultado[col].fillna("C")

    resultado["abc_combinada"] = resultado["abc_faturamento"] + "/" + resultado["abc_margem"] + "/" + resultado["abc_giro"]

    resultado["score"] = resultado.apply(calcular_score_produto, axis=1)
    resultado["acao_recomendada"] = resultado.apply(recomendar_acao, axis=1)
    return resultado


def calcular_score_produto(row) -> int:
    pontos = 0
    abc_pontos = {"A": 25, "B": 15, "C": 5}

    pontos += abc_pontos.get(row.get("abc_faturamento", "C"), 5)
    pontos += abc_pontos.get(row.get("abc_margem", "C"), 5)
    pontos += abc_pontos.get(row.get("abc_giro", "C"), 5)

    margem = row.get("margem_percentual", 0)
    if margem >= 0.40:
        pontos += 15
    elif margem >= 0.25:
        pontos += 10
    elif margem >= 0.15:
        pontos += 5

    if row.get("produto_estrategico", False):
        pontos += 8

    dias_vencer = row.get("dias_para_vencer", np.nan)
    if pd.notna(dias_vencer):
        if dias_vencer < 0:
            pontos -= 35
        elif dias_vencer <= 30:
            pontos -= 20
        elif dias_vencer <= 60:
            pontos -= 12
        elif dias_vencer <= 90:
            pontos -= 6

    cobertura = row.get("dias_cobertura", np.inf)
    if row.get("abc_giro", "C") == "C" and cobertura not in [np.inf, -np.inf]:
        if cobertura > 120:
            pontos -= 12

    return int(max(0, min(100, round(pontos))))


def recomendar_acao(row) -> str:
    estoque = row.get("estoque_atual", 0)
    minimo = row.get("estoque_minimo", 0)
    maximo = row.get("estoque_maximo", 0)
    abc_fat = row.get("abc_faturamento", "C")
    abc_margem = row.get("abc_margem", "C")
    abc_giro = row.get("abc_giro", "C")
    margem_pct = row.get("margem_percentual", 0)
    dias_vencer = row.get("dias_para_vencer", np.nan)
    cobertura = row.get("dias_cobertura", np.inf)

    if pd.notna(dias_vencer) and dias_vencer < 0:
        return "Bloquear e tratar como produto vencido"

    if pd.notna(dias_vencer) and dias_vencer <= 30:
        return "Ação imediata: validade crítica, aplicar regra sanitária e campanha se permitido"

    if estoque <= minimo and (abc_giro == "A" or abc_fat == "A" or row.get("produto_estrategico", False)):
        return "Compra urgente: item importante com estoque baixo"

    if abc_fat == "A" and abc_margem == "C":
        return "Revisar preço, custo ou fornecedor: vende muito, mas lucra pouco"

    if abc_fat == "A" and abc_margem == "A" and abc_giro == "A":
        return "Produto estratégico: recomprar, destacar e evitar ruptura"

    if abc_fat == "C" and abc_margem == "A":
        return "Produto oculto com boa margem: melhorar exposição"

    if abc_giro == "C" and estoque > minimo and cobertura not in [np.inf, -np.inf] and cobertura > 120:
        return "Capital parado: suspender compra e avaliar promoção"

    if margem_pct < 0.15 and row.get("faturamento_liquido", 0) > 0:
        return "Margem baixa: revisar preço ou fornecedor"

    if maximo > 0 and estoque > maximo:
        return "Excesso de estoque: suspender compra"

    if pd.notna(dias_vencer) and dias_vencer <= 90:
        return "Monitorar validade: aplicar FEFO"

    return "Manter monitoramento"


def calcular_recompra(df, prazo_entrega=7, dias_seguranca=10):
    base = df.copy()
    base["demanda_no_prazo"] = base["venda_media_diaria"] * prazo_entrega
    base["estoque_seguranca_sugerido"] = base["venda_media_diaria"] * dias_seguranca
    base["ponto_pedido"] = base["estoque_minimo"] + base["demanda_no_prazo"] + base["estoque_seguranca_sugerido"]

    necessidade = base["ponto_pedido"] - base["estoque_atual"]
    base["sugestao_recompra"] = np.where(necessidade > 0, np.ceil(necessidade), 0)

    # Limitar ao estoque máximo se ele estiver preenchido.
    espaco_max = np.where(base["estoque_maximo"] > 0, np.maximum(base["estoque_maximo"] - base["estoque_atual"], 0), base["sugestao_recompra"])
    base["sugestao_recompra"] = np.minimum(base["sugestao_recompra"], espaco_max)

    base["valor_estimado_compra"] = base["sugestao_recompra"] * base["custo"]
    return base


def produto_label_map(produtos):
    ativos = produtos[produtos["ativo"] == True].copy()
    return {f"{r['codigo']} - {r['nome']}": r["codigo"] for _, r in ativos.iterrows()}


def obter_produto(produtos, codigo):
    linha = produtos[produtos["codigo"] == codigo]
    if linha.empty:
        return None
    return linha.iloc[0]


# ============================================================
# FLUXO PRINCIPAL
# ============================================================

if not sistema_configurado():
    tela_configuracao_inicial()
    st.stop()

produtos, vendas, perdas, rupturas = carregar_bases()

st.sidebar.title("💊 Farmácia")
st.sidebar.caption("Gestão inteligente de estoque")

with st.sidebar.expander("Período de análise", expanded=True):
    inicio = st.date_input("Data inicial", value=date.today() - timedelta(days=90))
    fim = st.date_input("Data final", value=date.today())

    if inicio > fim:
        st.error("Data inicial maior que a data final.")
        st.stop()

with st.sidebar.expander("Configuração da Curva ABC"):
    limite_a = st.slider("Classe A até", min_value=0.50, max_value=0.90, value=0.80, step=0.05)
    min_limite_b = round(float(limite_a + 0.05), 2)
    limite_b = st.slider("Classe B até", min_value=min_limite_b, max_value=0.99, value=max(0.95, min_limite_b), step=0.01)

with st.sidebar.expander("Administração"):
    if st.button("Reimportar estoque inicial"):
        for arq in [PRODUTOS_FILE, VENDAS_FILE, PERDAS_FILE, RUPTURAS_FILE]:
            if arq.exists():
                arq.unlink()
        st.rerun()

metricas = calcular_abc_completo(produtos, vendas, inicio, fim, limite_a, limite_b)
recompra = calcular_recompra(metricas)

st.title("💊 Gestão Inteligente de Estoque para Farmácias")
st.markdown("Base configurada a partir do CSV inicial de estoque. Use as abas para vender, controlar e analisar a lucratividade.")

tabs = st.tabs([
    "📊 Dashboard",
    "📦 Produtos",
    "🧾 Vendas",
    "📈 Curva ABC",
    "🧠 Recomendações",
    "⏰ Validade/FEFO",
    "🛒 Recompra",
    "⚠️ Perdas/Rupturas",
    "⬇️ Importar/Exportar",
])


# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:
    st.header("Dashboard executivo")

    faturamento = metricas["faturamento_liquido"].sum()
    margem = metricas["margem_total"].sum()
    margem_pct = margem / faturamento if faturamento > 0 else 0
    valor_estoque = metricas["valor_estoque"].sum()
    capital_parado = metricas[
        (metricas["abc_giro"] == "C") &
        (metricas["estoque_atual"] > metricas["estoque_minimo"])
    ]["valor_estoque"].sum()
    estoque_critico = metricas[metricas["estoque_atual"] <= metricas["estoque_minimo"]].shape[0]
    vencendo_90 = metricas[(metricas["dias_para_vencer"].notna()) & (metricas["dias_para_vencer"] <= 90)].shape[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Faturamento no período", moeda(faturamento))
    c2.metric("Lucro bruto estimado", moeda(margem))
    c3.metric("Margem média", porcentagem(margem_pct))
    c4.metric("Valor em estoque", moeda(valor_estoque))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Capital parado estimado", moeda(capital_parado))
    c6.metric("Produtos em estoque crítico", estoque_critico)
    c7.metric("Produtos vencendo em até 90 dias", vencendo_90)
    c8.metric("Produtos cadastrados", produtos.shape[0])

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Top produtos por lucro bruto")
        top = metricas.sort_values("margem_total", ascending=False).head(10)
        mostrar_dataframe(
            top,
            ["codigo", "nome", "categoria", "margem_total", "faturamento_liquido", "score", "acao_recomendada"],
            use_container_width=True,
            hide_index=True,
        )
        if not top.empty:
            st.bar_chart(top.set_index("nome")["margem_total"])

    with col2:
        st.subheader("Atenções prioritárias")
        atencao = metricas[
            (metricas["estoque_atual"] <= metricas["estoque_minimo"]) |
            ((metricas["dias_para_vencer"].notna()) & (metricas["dias_para_vencer"] <= 90)) |
            (metricas["acao_recomendada"].str.contains("Capital parado|Margem baixa|Compra urgente", case=False, na=False))
        ].sort_values("score")
        mostrar_dataframe(
            atencao,
            ["codigo", "nome", "estoque_atual", "estoque_minimo", "dias_para_vencer", "score", "acao_recomendada"],
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# PRODUTOS
# ============================================================

with tabs[1]:
    st.header("Produtos importados e base interna")

    st.info("Esta tabela é a base interna criada a partir do CSV inicial. Você pode corrigir custos, preços, validade, mínimo, máximo e localização.")

    produtos_editados = st.data_editor(
        dataframe_seguro(produtos),
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
    )

    if st.button("💾 Salvar alterações em produtos"):
        salvar_csv(normalizar_produtos(produtos_editados), PRODUTOS_FILE)
        st.success("Produtos salvos.")
        st.rerun()

    st.download_button(
        "⬇️ Baixar base interna de produtos em CSV",
        data=csv_download(produtos),
        file_name="produtos_base_interna.csv",
        mime="text/csv",
    )


# ============================================================
# VENDAS
# ============================================================

with tabs[2]:
    st.header("Registro de vendas")

    mapa_produtos = produto_label_map(produtos)

    if not mapa_produtos:
        st.warning("Não há produtos ativos cadastrados.")
    else:
        with st.form("form_venda"):
            c1, c2, c3 = st.columns(3)
            produto_sel = c1.selectbox("Produto", list(mapa_produtos.keys()))
            codigo = mapa_produtos[produto_sel]
            produto = obter_produto(produtos, codigo)

            data_venda = c2.date_input("Data", value=date.today())
            quantidade = c3.number_input("Quantidade", min_value=1.0, value=1.0, step=1.0)

            c4, c5, c6 = st.columns(3)
            preco = c4.number_input("Preço unitário", min_value=0.0, value=float(produto["preco_venda"]), step=0.01)
            desconto = c5.number_input("Desconto unitário", min_value=0.0, value=0.0, step=0.01)
            atendente = c6.text_input("Atendente")

            salvar_venda = st.form_submit_button("Registrar venda e baixar estoque")

            if salvar_venda:
                nova = pd.DataFrame([[
                    data_venda,
                    codigo,
                    quantidade,
                    preco,
                    float(produto["custo"]),
                    desconto,
                    atendente,
                ]], columns=COL_VENDAS)

                vendas_atualizadas = pd.concat([vendas, nova], ignore_index=True)
                produtos_atualizados = produtos.copy()
                idx = produtos_atualizados["codigo"] == codigo
                produtos_atualizados.loc[idx, "estoque_atual"] = (
                    produtos_atualizados.loc[idx, "estoque_atual"].astype(float) - quantidade
                ).clip(lower=0)

                salvar_csv(vendas_atualizadas, VENDAS_FILE)
                salvar_csv(produtos_atualizados, PRODUTOS_FILE)
                st.success("Venda registrada.")
                st.rerun()

    st.subheader("Histórico de vendas")
    mostrar_dataframe(vendas.sort_values("data", ascending=False), use_container_width=True, hide_index=True)


# ============================================================
# CURVA ABC
# ============================================================

with tabs[3]:
    st.header("Curva ABC")

    c1, c2 = st.columns(2)
    metrica_escolhida = c1.selectbox(
        "Métrica",
        [
            ("Faturamento", "faturamento_liquido", "abc_faturamento"),
            ("Margem", "margem_total", "abc_margem"),
            ("Giro", "quantidade_vendida", "abc_giro"),
        ],
        format_func=lambda x: x[0],
    )
    classes = c2.multiselect("Classes", ["A", "B", "C"], default=["A", "B", "C"])

    nome_metrica, coluna_metrica, coluna_abc = metrica_escolhida
    abc_view = metricas[metricas[coluna_abc].isin(classes)].sort_values(coluna_metrica, ascending=False)

    colunas_abc_view = colunas_unicas([
        "codigo", "nome", "categoria", coluna_metrica, coluna_abc,
        "abc_faturamento", "abc_margem", "abc_giro", "abc_combinada",
        "estoque_atual", "dias_cobertura", "score", "acao_recomendada"
    ])

    mostrar_dataframe(
        abc_view,
        colunas_abc_view,
        use_container_width=True,
        hide_index=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Distribuição por classe")
        dist = abc_view.groupby(coluna_abc, as_index=False).agg(
            produtos=("codigo", "count"),
            valor=(coluna_metrica, "sum"),
        )
        mostrar_dataframe(dist, use_container_width=True, hide_index=True)
        if not dist.empty:
            st.bar_chart(dist.set_index(coluna_abc)["valor"])

    with col2:
        st.subheader("Pareto dos principais produtos")
        pareto = abc_view.sort_values(coluna_metrica, ascending=False).head(20)
        if not pareto.empty:
            st.bar_chart(pareto.set_index("nome")[coluna_metrica])

    st.download_button(
        "⬇️ Baixar análise ABC em CSV",
        data=csv_download(abc_view),
        file_name="curva_abc.csv",
        mime="text/csv",
    )


# ============================================================
# RECOMENDAÇÕES
# ============================================================

with tabs[4]:
    st.header("Recomendações automáticas")

    filtro = st.text_input("Filtrar ação recomendada")
    rec = metricas.copy()
    if filtro:
        rec = rec[rec["acao_recomendada"].str.contains(filtro, case=False, na=False)]

    rec = rec.sort_values(["score", "margem_total"], ascending=[False, False])

    mostrar_dataframe(
        rec,
        [
            "codigo", "nome", "categoria", "score",
            "abc_faturamento", "abc_margem", "abc_giro",
            "estoque_atual", "dias_para_vencer",
            "margem_percentual", "acao_recomendada"
        ],
        use_container_width=True,
        hide_index=True,
    )

    resumo = rec.groupby("acao_recomendada", as_index=False).agg(
        quantidade=("codigo", "count"),
        valor_estoque=("valor_estoque", "sum"),
    ).sort_values("quantidade", ascending=False)

    st.subheader("Resumo por tipo de ação")
    mostrar_dataframe(resumo, use_container_width=True, hide_index=True)


# ============================================================
# VALIDADE/FEFO
# ============================================================

with tabs[5]:
    st.header("Validade e FEFO")

    validade_view = metricas.sort_values(["dias_para_vencer", "valor_estoque"], ascending=[True, False])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vencidos", int((validade_view["dias_para_vencer"] < 0).sum()))
    c2.metric("Até 30 dias", int(((validade_view["dias_para_vencer"] >= 0) & (validade_view["dias_para_vencer"] <= 30)).sum()))
    c3.metric("Até 90 dias", int(((validade_view["dias_para_vencer"] >= 0) & (validade_view["dias_para_vencer"] <= 90)).sum()))
    c4.metric("Até 180 dias", int(((validade_view["dias_para_vencer"] >= 0) & (validade_view["dias_para_vencer"] <= 180)).sum()))

    mostrar_dataframe(
        validade_view,
        [
            "codigo", "nome", "categoria", "lote", "validade", "dias_para_vencer",
            "status_validade", "estoque_atual", "valor_estoque", "acao_recomendada"
        ],
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# RECOMPRA
# ============================================================

with tabs[6]:
    st.header("Sugestão automática de recompra")

    c1, c2 = st.columns(2)
    prazo_entrega = c1.number_input("Prazo médio de entrega em dias", min_value=1, value=7, step=1)
    dias_seguranca = c2.number_input("Dias de estoque de segurança", min_value=0, value=10, step=1)

    recompra_view = calcular_recompra(metricas, prazo_entrega, dias_seguranca)
    somente_comprar = st.checkbox("Mostrar apenas itens com sugestão de compra", value=True)
    if somente_comprar:
        recompra_view = recompra_view[recompra_view["sugestao_recompra"] > 0]

    recompra_view = recompra_view.sort_values(["sugestao_recompra", "score"], ascending=[False, False])

    st.metric("Valor estimado da compra sugerida", moeda(recompra_view["valor_estimado_compra"].sum()))

    mostrar_dataframe(
        recompra_view,
        [
            "codigo", "nome", "categoria", "fornecedor", "estoque_atual",
            "estoque_minimo", "estoque_maximo", "venda_media_diaria",
            "ponto_pedido", "sugestao_recompra", "valor_estimado_compra",
            "abc_giro", "abc_margem", "acao_recomendada"
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "⬇️ Baixar sugestão de recompra em CSV",
        data=csv_download(recompra_view),
        file_name="sugestao_recompra.csv",
        mime="text/csv",
    )


# ============================================================
# PERDAS E RUPTURAS
# ============================================================

with tabs[7]:
    st.header("Perdas e rupturas")

    mapa_produtos = produto_label_map(produtos)
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Registrar perda")
        with st.form("form_perda"):
            produto_sel = st.selectbox("Produto", list(mapa_produtos.keys()), key="perda_produto") if mapa_produtos else None
            data_perda = st.date_input("Data da perda", value=date.today())
            qtd = st.number_input("Quantidade perdida", min_value=1.0, value=1.0, step=1.0)
            motivo = st.selectbox("Motivo", ["Vencimento", "Avaria", "Quebra", "Furto", "Erro de lançamento", "Devolução", "Extravio", "Outro"])
            observacao = st.text_area("Observação", key="obs_perda")

            salvar_perda = st.form_submit_button("Registrar perda e baixar estoque")

            if salvar_perda and produto_sel:
                codigo = mapa_produtos[produto_sel]
                produto = obter_produto(produtos, codigo)
                valor_estimado = float(produto["custo"]) * qtd

                nova = pd.DataFrame([[data_perda, codigo, qtd, motivo, valor_estimado, observacao]], columns=COL_PERDAS)
                perdas_atualizadas = pd.concat([perdas, nova], ignore_index=True)

                produtos_atualizados = produtos.copy()
                idx = produtos_atualizados["codigo"] == codigo
                produtos_atualizados.loc[idx, "estoque_atual"] = (
                    produtos_atualizados.loc[idx, "estoque_atual"].astype(float) - qtd
                ).clip(lower=0)

                salvar_csv(perdas_atualizadas, PERDAS_FILE)
                salvar_csv(produtos_atualizados, PRODUTOS_FILE)
                st.success("Perda registrada.")
                st.rerun()

    with col2:
        st.subheader("Registrar venda perdida / ruptura")
        with st.form("form_ruptura"):
            produto_sel = st.selectbox("Produto procurado", list(mapa_produtos.keys()), key="ruptura_produto") if mapa_produtos else None
            data_rup = st.date_input("Data da procura", value=date.today())
            qtd_sol = st.number_input("Quantidade solicitada", min_value=1.0, value=1.0, step=1.0)
            obs = st.text_area("Observação", key="obs_ruptura")

            salvar_rup = st.form_submit_button("Registrar ruptura")

            if salvar_rup and produto_sel:
                codigo = mapa_produtos[produto_sel]
                nova = pd.DataFrame([[data_rup, codigo, qtd_sol, obs]], columns=COL_RUPTURAS)
                rupturas_atualizadas = pd.concat([rupturas, nova], ignore_index=True)
                salvar_csv(rupturas_atualizadas, RUPTURAS_FILE)
                st.success("Ruptura registrada.")
                st.rerun()

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Perdas registradas")
        mostrar_dataframe(perdas.sort_values("data", ascending=False), use_container_width=True, hide_index=True)
        st.metric("Total de perdas estimadas", moeda(perdas["valor_estimado"].sum() if not perdas.empty else 0))

    with c2:
        st.subheader("Rupturas / vendas perdidas")
        rupt_view = rupturas.merge(produtos[["codigo", "nome", "preco_venda", "custo"]], on="codigo", how="left")
        if not rupt_view.empty:
            rupt_view["venda_perdida_estimada"] = rupt_view["quantidade_solicitada"] * rupt_view["preco_venda"].fillna(0)
            rupt_view["margem_perdida_estimada"] = rupt_view["quantidade_solicitada"] * (rupt_view["preco_venda"].fillna(0) - rupt_view["custo"].fillna(0))
        mostrar_dataframe(rupt_view.sort_values("data", ascending=False) if not rupt_view.empty else rupt_view, use_container_width=True, hide_index=True)
        if not rupt_view.empty:
            st.metric("Venda perdida estimada", moeda(rupt_view["venda_perdida_estimada"].sum()))


# ============================================================
# IMPORTAR / EXPORTAR
# ============================================================

with tabs[8]:
    st.header("Importar e exportar dados")

    st.subheader("Exportar bases internas")
    c1, c2, c3, c4 = st.columns(4)

    c1.download_button("Produtos CSV", csv_download(produtos), "produtos.csv", "text/csv")
    c2.download_button("Vendas CSV", csv_download(vendas), "vendas.csv", "text/csv")
    c3.download_button("Perdas CSV", csv_download(perdas), "perdas.csv", "text/csv")
    c4.download_button("Rupturas CSV", csv_download(rupturas), "rupturas.csv", "text/csv")

    st.divider()
    st.subheader("Adicionar nova planilha de estoque")
    st.warning("Esta opção substitui a base atual de produtos. As vendas, perdas e rupturas serão mantidas.")

    novo_csv = st.file_uploader("Enviar nova planilha de estoque para substituir produtos", type=["csv", "xlsx", "xls"], key="novo_csv_produtos")
    if novo_csv:
        df_novo = ler_planilha_upload(novo_csv)
        mapa_detectado = detectar_mapeamento_colunas(df_novo)
        mostrar_dataframe(df_novo.head(10), use_container_width=True)

        opcoes = [""] + colunas_unicas(list(df_novo.columns))
        mapa_final = {}
        for destino in COL_PRODUTOS:
            default = mapa_detectado.get(destino, "")
            index_default = opcoes.index(default) if default in opcoes else 0
            mapa_final[destino] = st.selectbox(f"Campo {destino}", opcoes, index=index_default, key=f"novo_{destino}")

        if st.button("Substituir base de produtos"):
            if not mapa_final.get("nome") or not mapa_final.get("estoque_atual"):
                st.error("Selecione pelo menos os campos obrigatórios: nome e estoque_atual.")
                st.stop()
            produtos_novos = padronizar_estoque_inicial(df_novo, mapa_final)
            if produtos_novos.empty:
                st.error("Nenhum produto válido foi identificado na nova planilha.")
                st.stop()
            salvar_csv(produtos_novos, PRODUTOS_FILE)
            st.success("Base de produtos substituída.")
            st.rerun()

    st.divider()
    st.subheader("Informações técnicas")
    st.code(
        f"Pasta de dados: {DATA_DIR.resolve()}\n"
        f"Produtos: {PRODUTOS_FILE}\n"
        f"Vendas: {VENDAS_FILE}\n"
        f"Perdas: {PERDAS_FILE}\n"
        f"Rupturas: {RUPTURAS_FILE}",
        language="text",
    )
