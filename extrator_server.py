"""
Servidor local de extração de leilões — Douglas Rosa
Roda em http://localhost:5001
Inicie pelo arquivo: INICIAR EXTRATOR.bat
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
from bs4 import BeautifulSoup
import re, json

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─────────────────────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────────────────────────────────────

def clean(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()

def fix_url(href, base='https:'):
    if not href:
        return ''
    if href.startswith('//'):
        return base + href
    if href.startswith('/'):
        return ''   # relativo sem domínio — descartamos
    return href

def parse_date_br(text):
    """Converte 'DD/MM/YYYY às HH:MM' → 'YYYY-MM-DDTHH:MM'"""
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})[^\d]*(\d{2}):(\d{2})', text)
    if m:
        dd, mm, yy, hr, mn = m.groups()
        return f'{yy}-{mm}-{dd}T{hr}:{mn}'
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    if m:
        dd, mm, yy = m.groups()
        return f'{yy}-{mm}-{dd}T00:00'
    return ''

def product_detail_map(soup):
    """
    Lê todos os div.product-detail e monta um dict
    Ex: {'Valor atual': 'R$ 8.546,87', 'Processo': '1003369-...'}
    """
    result = {}
    for el in soup.find_all(class_='product-detail'):
        parts = [p.strip() for p in el.get_text(separator='|').split('|') if p.strip()]
        if len(parts) >= 2:
            result[parts[0]] = parts[1]
        elif len(parts) == 1:
            result[parts[0]] = ''
    return result


# ─────────────────────────────────────────────────────────────────────────────
# EXTRATOR ESPECÍFICO — grupolance.com.br
# ─────────────────────────────────────────────────────────────────────────────

def extract_grupolance(soup, url):
    # ── título ──
    h1 = soup.find('h1')
    titulo = clean(h1.get_text()) if h1 else ''

    # ── descrição do lote ──
    descricao = ''
    for h2 in soup.find_all('h2'):
        if 'descri' in h2.get_text().lower():
            sib = h2.find_next_sibling()
            if sib:
                descricao = clean(sib.get_text())[:600]
            break

    # ── mapa de detalhes ──
    det = product_detail_map(soup)

    avaliacao  = det.get('Valor de avaliação', '') or det.get('Valor de Avaliacao', '')
    lance      = det.get('Valor atual', '')
    incremento = det.get('Incremento', '')
    processo   = det.get('Processo', '')
    leilao_num = det.get('Leilão', '') or det.get('Leilao', '')
    autor      = det.get('Autor', '')
    reu        = det.get('Réu', '') or det.get('Reu', '')
    vara       = det.get('Vara', '')
    comarca    = det.get('Comarca', '')

    # ── praça ativa (data + modalidade) ──
    data_leilao = ''
    modalidade  = ''
    praça_ativa = soup.find(class_=re.compile(r'product-instance.*active'))
    if praça_ativa:
        txt = praça_ativa.get_text(separator=' ', strip=True)
        data_leilao = parse_date_br(txt)
        if '2ª' in txt or '2a' in txt.lower():
            modalidade = '2ª Praça'
        elif '1ª' in txt or '1a' in txt.lower():
            modalidade = '1ª Praça'
    # fallback: última praça listada
    if not data_leilao:
        for el in soup.find_all(class_='product-instance'):
            txt = el.get_text(separator=' ', strip=True)
            data_leilao = parse_date_br(txt)

    # ── área e cidade ──
    m_area = re.search(r'([\d,]+)\s*m[²2²]', titulo, re.IGNORECASE)
    area   = m_area.group(0) if m_area else ''
    m_cid  = re.search(r',\s*([^,]+/[A-Z]{2})\s*$', titulo)
    cidade = m_cid.group(1).strip() if m_cid else comarca

    # ── tipo ──
    tipo = ''
    for t in ['Apartamento', 'Casa', 'Terreno', 'Sala Comercial', 'Galpão', 'Loja']:
        if t.lower() in titulo.lower():
            tipo = t; break

    # ── edital (PDF) ──
    edital = ''
    for a in soup.find_all('a', href=True):
        href = a['href']
        txt  = a.get_text(strip=True).lower()
        if 'edital' in txt or 'edital' in href.lower():
            edital = fix_url(href)
            break

    # ── matrícula ──
    matricula = ''
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href in ('#', '', 'javascript:void(0)', 'javascript:;'):
            continue
        txt  = a.get_text(strip=True).lower()
        if 'matr' in txt or 'matr' in href.lower():
            matricula = fix_url(href)
            if matricula:
                break

    # ── fotos (full size, sem _thumb) ──
    fotos = []
    seen  = set()
    # og:image primeiro
    og = soup.find('meta', property='og:image')
    if og and og.get('content'):
        fotos.append(og['content'])
        seen.add(og['content'])

    for img in soup.find_all('img', src=True):
        src = img['src']
        if 'cdn.grupolance' in src or 'batches' in src:
            full = src.replace('_thumb', '')
            if full not in seen:
                fotos.append(full)
                seen.add(full)

    # ── leiloeiro ──
    leiloeiro = 'Grupo Lance'

    return {
        'ok':        True,
        'titulo':    titulo,
        'descricao': descricao,
        'foto':      fotos[0] if fotos else '',
        'images':    fotos[:8],
        'avaliacao': avaliacao,
        'lance':     lance,
        'incremento': incremento,
        'data':      data_leilao,
        'leiloeiro': leiloeiro,
        'area':      area,
        'cidade':    cidade,
        'tipo':      tipo,
        'modalidade': modalidade,
        'edital':    edital,
        'matricula': matricula,
        'processo':  processo,
        'leilao_num': leilao_num,
        'autor':     autor,
        'reu':       reu,
        'vara':      vara,
        'comarca':   comarca,
        'url':       url,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXTRATOR ESPECÍFICO — freitasleiloeiro.com.br
# ─────────────────────────────────────────────────────────────────────────────

def extract_freitasleiloeiro(soup, url):
    text = soup.get_text(' ', strip=True)

    # ── IDs da URL (leilaoId e loteNumero) ──
    m_lid  = re.search(r'leilaoId=(\d+)',   url)
    m_lnum = re.search(r'loteNumero=(\d+)', url)
    leilao_id = m_lid.group(1)  if m_lid  else ''
    lote_num  = m_lnum.group(1).zfill(3) if m_lnum else ''   # ex: "007"

    # ── Título do leilão (h4) ──
    h4 = soup.find('h4', class_=re.compile(r'mt-')) or soup.find('h4')
    titulo_leilao = clean(h4.get_text()) if h4 else ''

    # ── Tipo e Cidade (div.text-secondary.fs-5) ──
    tipo_cidade_el = None
    for el in soup.find_all(class_='text-secondary'):
        cls = ' '.join(el.get('class', []))
        if 'fs-5' in cls:
            tipo_cidade_el = el
            break
    tipo_cidade = clean(tipo_cidade_el.get_text()) if tipo_cidade_el else ''
    tipo   = tipo_cidade.split('|')[0].strip() if '|' in tipo_cidade else ''
    cidade = tipo_cidade.split('|')[1].strip() if '|' in tipo_cidade else ''

    # ── Endereço (div.text-secondary com logradouro) ──
    endereco = ''
    for el in soup.find_all(class_='text-secondary'):
        t = clean(el.get_text())
        if re.search(r'\b(Rua|Av\.?|Avenida|Alameda|Travessa|Praça|Rod\.?|Rodovia|Estrada)\b', t, re.IGNORECASE):
            endereco = t
            break

    # ── Descrição completa do lote (div sem classe que COMEÇA com cidade/bairro) ──
    descricao = ''
    for div in soup.find_all('div'):
        if div.get('class'):
            continue
        # Só pegar divs folha (sem divs filhas) para evitar blocos-pai
        if div.find('div'):
            continue
        t = clean(div.get_text())
        # Descrição do lote começa com a cidade ou "Bairro" e tem m²
        if (len(t) > 50 and len(t) < 800
                and any(k in t for k in ['m²', 'Matr', 'Bairro', 'Loteamento'])
                and re.match(r'^[A-ZÀ-Ú]', t)):
            descricao = t[:600]
            break

    # ── Área (da descrição) ──
    area = ''
    m_constr = re.search(r'constr\.\s*([\d,.]+\s*m[²2])', descricao, re.IGNORECASE)
    m_terr   = re.search(r'terr\.\s*([\d,.]+\s*m[²2])',   descricao, re.IGNORECASE)
    if m_constr and m_terr:
        area = f'terr. {m_terr.group(1)} / constr. {m_constr.group(1)}'
    elif m_constr:
        area = m_constr.group(1)
    elif m_terr:
        area = m_terr.group(1)
    else:
        m_a = re.search(r'([\d,.]+\s*m[²2])', descricao, re.IGNORECASE)
        if m_a:
            area = m_a.group(1)

    # ── Data e Hora (box-menu-detalhes) ──
    data_leilao = ''
    lote_box = soup.find(class_='box-menu-detalhes')
    if lote_box:
        t = lote_box.get_text(separator='|', strip=True)
        m_d = re.search(r'Data do Leil[aã]o\|(\d{2}/\d{2}/\d{4})', t)
        m_h = re.search(r'Hor[aá]rio\|(\d{2}:\d{2})',               t)
        if m_d:
            dd, mm, yy = m_d.group(1).split('/')
            hora = m_h.group(1) if m_h else '00:00'
            data_leilao = f'{yy}-{mm}-{dd}T{hora}'

    # ── Tabela (leiloeiro, modalidade) ──
    leiloeiro = 'Freitas Leiloeiro'
    modalidade_site = ''
    for tbl in soup.find_all('table'):
        for row in tbl.find_all('tr'):
            cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
            if len(cells) >= 2:
                if 'Leiloeiro' in cells[0]:
                    leiloeiro = cells[1]
                if 'Modalidade' in cells[0]:
                    modalidade_site = cells[1]

    # ── Modalidade / praça ──
    modalidade = ''
    tl = titulo_leilao.lower()
    if 'segundo' in tl or '2º' in tl or '2°' in tl:
        modalidade = '2ª Praça'
    elif 'primeiro' in tl or '1º' in tl or '1°' in tl:
        modalidade = '1ª Praça'
    if 'extrajudicial' in tl or 'aliena' in tl or 'fiduci' in tl:
        sufixo = ' — Extrajudicial' if modalidade else 'Leilão Extrajudicial'
        modalidade = (modalidade + sufixo) if modalidade else sufixo

    # ── Autor (credor — após "FIDUCIÁRIA -" ou "JUDICIAL -") ──
    autor = ''
    # Pega o último segmento após " - " (o credor/banco é sempre o último)
    m_aut = re.search(r'[-–]\s*([^-–]+)\s*$', titulo_leilao)
    if m_aut:
        autor = m_aut.group(1).strip()

    # ── Valores: 1ª praça = avaliação / 2ª praça = lance mínimo ──
    avaliacao = ''
    lance     = ''
    m1 = re.search(r'1[ºo°°]\s*Leil[aã]o[^\d]{0,30}R\$\s*([\d.]+,\d{2})', text, re.IGNORECASE)
    m2 = re.search(r'2[ºo°°]\s*Leil[aã]o[^\d]{0,30}R\$\s*([\d.]+,\d{2})', text, re.IGNORECASE)
    if m1: avaliacao = 'R$ ' + m1.group(1)
    if m2: lance     = 'R$ ' + m2.group(1)
    # fallback: dois primeiros valores da página
    if not avaliacao or not lance:
        prices = re.findall(r'R\$\s*([\d.]+,\d{2})', text)
        if not avaliacao and prices:         avaliacao = 'R$ ' + prices[0]
        if not lance and len(prices) > 1:    lance     = 'R$ ' + prices[1]

    # ── Incremento ──
    incremento = ''
    m_inc = re.search(r'R\$\s*([\d.]+,\d{2})\s*Incremento', text, re.IGNORECASE)
    if not m_inc:
        m_inc = re.search(r'Incremento[^R]{0,20}R\$\s*([\d.]+,\d{2})', text, re.IGNORECASE)
    if m_inc:
        incremento = 'R$ ' + m_inc.group(1)

    # ── Edital e Matrícula ──
    edital = ''
    matricula = ''
    for a in soup.find_all('a', href=True):
        href = a['href']
        if not href.startswith('http'):
            continue
        txt = a.get_text(strip=True).lower()
        if 'edital' in txt:
            # prefere o edital específico do lote (contém lote_num no path)
            if lote_num and lote_num in href:
                edital = href
            elif not edital:
                edital = href
        if 'matr' in txt and href.lower().endswith('.pdf') and not matricula:
            matricula = href

    # ── Título formatado ──
    if endereco and tipo:
        titulo = f'{tipo} — {endereco}'
    elif endereco:
        titulo = endereco
    else:
        titulo = titulo_leilao[:120]

    return {
        'ok':        True,
        'titulo':    titulo,
        'descricao': descricao or f'{titulo_leilao}. {endereco}'.strip('. '),
        'foto':      '',
        'images':    [],
        'avaliacao': avaliacao,
        'lance':     lance,
        'incremento': incremento,
        'data':      data_leilao,
        'leiloeiro': leiloeiro,
        'area':      area,
        'cidade':    cidade,
        'tipo':      tipo,
        'modalidade': modalidade,
        'edital':    edital,
        'matricula': matricula,
        'processo':  '',
        'leilao_num': lote_num,
        'autor':     autor,
        'reu':       '',
        'vara':      '',
        'comarca':   cidade,
        'url':       url,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXTRATOR ESPECÍFICO — portalbayit.com.br  (plataforma Degrau / dg- classes)
# ─────────────────────────────────────────────────────────────────────────────

def extract_portalbayit(soup, url):
    """
    Funciona com qualquer site que use a plataforma Degrau (classes dg-).
    Detectado pela presença de h1.dg-lote-titulo ou meta plataforma_de_leilão.
    """

    # ── Nome e código ──
    nome_el = soup.find('span', class_='dg-lote-nome')
    nome = clean(nome_el.get_text()) if nome_el else ''
    if not nome:
        h1 = soup.find('h1', class_='dg-lote-titulo')
        nome = clean(h1.get_text()) if h1 else ''

    cod_el  = soup.find('span', class_='dg-lote-nome-titulo-codigo')
    leilao_num = clean(cod_el.get_text()).replace('Cód do leilão:', '').strip() if cod_el else ''

    # ── Tipo ──
    tipo = ''
    for t in ['Apartamento', 'Casa', 'Terreno', 'Sala Comercial', 'Galpão', 'Loja']:
        if t.lower() in nome.lower():
            tipo = t; break
    if not tipo:
        cat_el = soup.find('span', class_='dg-lote-titulo-categoria')
        cat = clean(cat_el.get_text()) if cat_el else ''
        for t in ['Apartamento', 'Casa', 'Terreno', 'Sala Comercial', 'Galpão']:
            if t.lower() in cat.lower():
                tipo = t; break

    # ── Avaliação e Incremento ──
    av_el = soup.find('strong', class_='ValorAvaliacao')
    avaliacao = 'R$ ' + av_el.get_text(strip=True).replace('R$', '').strip() if av_el else ''

    inc_el = soup.find('strong', class_='ValorIncremento')
    incremento = 'R$ ' + inc_el.get_text(strip=True).replace('R$', '').strip() if inc_el else ''

    # ── Área (ÁREA TOTAL preferida sobre ÁREA ÚTIL) ──
    area_total = area_util = ''
    for item in soup.find_all('div', class_=lambda c: c and 'info-detalhe-ctn' in c):
        tooltip = item.find('div', class_='dg-tooltip')
        val_el  = item.find('span', class_='dg-lote-cfgs-txt')
        if not (tooltip and val_el): continue
        label = tooltip.get_text(strip=True).upper()
        val   = val_el.get_text(strip=True)
        if 'm' in val.lower():
            if 'TOTAL' in label:
                area_total = val
            elif 'ÚTIL' in label or 'UTIL' in label:
                area_util = val
    area = area_total or area_util
    if area_total and area_util:
        area = f'Total: {area_total} / Útil: {area_util}'

    # ── Dados judiciais (dg-lote-descricao-info) ──
    processo = comarca = vara = autor = reu = acao = ''
    info_div = soup.find('div', class_='dg-lote-descricao-info')
    if info_div:
        lines = [l.strip() for l in info_div.get_text(separator='\n').splitlines() if l.strip()]
        i = 0
        while i < len(lines) - 1:
            lbl = lines[i].rstrip(':').lower()
            val = lines[i + 1].strip()
            if 'processo'  in lbl: processo = val
            elif 'comarca' in lbl: comarca  = val
            elif 'vara'    in lbl: vara     = val
            elif 'autor'   in lbl: autor    = val
            elif 'réu'     in lbl or 'reu' in lbl: reu  = val
            elif 'ação'    in lbl or 'acao' in lbl: acao = val
            i += 2

    # ── Modalidade (derivada da Ação) ──
    modalidade = ''
    al = acao.lower()
    if 'extrajudicial' in al:
        modalidade = 'Leilão Extrajudicial'
    elif 'execução' in al or 'judicial' in al:
        modalidade = '2ª Praça'

    # ── Endereço e Cidade ──
    end_div  = soup.find('div', class_='dg-lote-local-endereco')
    endereco = clean(end_div.get_text()) if end_div else ''

    cidade = ''
    if endereco:
        # "Rua Xxx, 174 - Paraíso - São Paulo - SP"
        parts = [p.strip() for p in endereco.split(' - ')]
        uf    = parts[-1]
        city  = parts[-2] if len(parts) >= 3 else ''
        if len(uf) == 2 and uf.isalpha():
            cidade = f'{city}/{uf}' if city else uf
        else:
            cidade = uf
    if not cidade and comarca:
        cidade = comarca

    # ── Descrição detalhada ──
    desc_div  = soup.find('div', class_='dg-lote-descricao-txt')
    descricao = clean(desc_div.get_text()) if desc_div else endereco

    # ── Documentos (edital e matrícula) ──
    edital = matricula = ''
    ul_docs = soup.find('ul', class_='jsLoteAnexos')
    if ul_docs:
        for li in ul_docs.find_all('li', class_='dg-lote-documentos-downloads__item'):
            # Texto do label (nó de texto direto, antes dos <a>)
            label_parts = []
            for node in li.children:
                if getattr(node, 'name', None) == 'a':
                    break
                t = str(node).strip()
                if t:
                    label_parts.append(t)
            label = ' '.join(label_parts).strip().lower()

            links = [a['href'] for a in li.find_all('a', href=True)
                     if a['href'] and a['href'] != 'javascript:void(0)']

            if not links:
                continue
            if 'edital' in label and not edital:
                edital = links[0]          # link "Visualizar" (primeiro)
            elif 'matr' in label and not matricula:
                matricula = links[0]

    # ── Foto ──
    foto = ''
    og_img = soup.find('meta', property='og:image')
    if og_img and og_img.get('content'):
        foto = og_img['content']
    else:
        main = soup.find('main', class_='dg-lote')
        if main:
            img = main.find('img', src=True)
            foto = img['src'] if img else ''

    # ── Galeria ──
    images = []
    main = soup.find('main', class_='dg-lote') or soup
    for img in main.find_all('img', src=True):
        src = img['src']
        if src and src.startswith('http') and src not in images:
            images.append(src)

    # ── Leiloeiro ──
    og_site = soup.find('meta', property='og:site_name')
    leiloeiro = clean(og_site['content']) if og_site and og_site.get('content') else 'Portal Bayit'

    # ── Título formatado ──
    titulo = f'{nome} | {cidade}' if cidade else nome

    return {
        'ok':         True,
        'titulo':     titulo,
        'descricao':  descricao or endereco,
        'foto':       foto,
        'images':     images[:8],
        'avaliacao':  avaliacao,
        'lance':      '',        # carregado via JS — não disponível no HTML estático
        'incremento': incremento,
        'data':       '',        # carregado via JS — não disponível no HTML estático
        'leiloeiro':  leiloeiro,
        'area':       area,
        'cidade':     cidade,
        'tipo':       tipo,
        'modalidade': modalidade,
        'edital':     edital,
        'matricula':  matricula,
        'processo':   processo,
        'leilao_num': leilao_num,
        'autor':      autor,
        'reu':        reu,
        'vara':       vara,
        'comarca':    comarca or cidade,
        'url':        url,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXTRATOR GENÉRICO (fallback para outros sites)
# ─────────────────────────────────────────────────────────────────────────────

def extract_generic(soup, url):
    def meta(prop):
        el = soup.find('meta', property=prop) or \
             soup.find('meta', attrs={'name': prop})
        return clean(el['content']) if el and el.get('content') else ''

    text = soup.get_text(' ', strip=True)

    h1    = soup.find('h1')
    titulo = clean(h1.get_text()) if h1 else (meta('og:title') or clean(soup.title.string or ''))
    # remove texto de compartilhamento social do título
    if titulo.startswith(';)') or 'adorei' in titulo.lower():
        titulo = meta('og:description') or titulo

    desc  = meta('og:description') or ''
    foto  = meta('og:image') or ''

    def find_money(keywords):
        for kw in keywords:
            m = re.search(rf'{kw}[^R]{{0,30}}R\$\s*([\d.,]+)', text, re.IGNORECASE)
            if m:
                return 'R$ ' + m.group(1)
        return ''

    avaliacao = find_money([r'avalia[çc][aã]o', r'valor\s+de\s+avalia', r'vr\.?\s+avalia'])
    lance     = find_money([r'lance\s+m[íi]nimo', r'lance\s+inicial', r'valor\s+m[íi]nimo', r'valor\s+atual'])

    if not avaliacao or not lance:
        prices = re.findall(r'R\$\s*[\d.,]+', text)
        if not avaliacao and prices:
            avaliacao = prices[0]
        if not lance and len(prices) > 1:
            lance = prices[1]

    data_leilao = parse_date_br(text)

    m_area = re.search(r'([\d,]+)\s*m[²2²]', text, re.IGNORECASE)
    area   = m_area.group(0) if m_area else ''

    m_cid  = re.search(r'([A-ZÀ-Ú][a-zà-ú]+(?:\s[A-ZÀ-Ú]?[a-zà-ú]+)*)\s*/\s*([A-Z]{2})\b', text)
    cidade = m_cid.group(0) if m_cid else ''

    pdfs = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        txt  = a.get_text(strip=True)
        if '.pdf' in href.lower() or any(k in txt.lower() for k in ['edital', 'matr', 'laudo']):
            full = fix_url(href)
            if full:
                pdfs.append({'url': full, 'label': txt})

    edital    = next((p['url'] for p in pdfs if 'edital' in p['label'].lower() + p['url'].lower()), '')
    matricula = next((p['url'] for p in pdfs if 'matr'   in p['label'].lower() + p['url'].lower()), '')

    tipo = ''
    for t in ['Apartamento', 'Casa', 'Terreno', 'Sala Comercial', 'Galpão']:
        if re.search(t, text, re.IGNORECASE):
            tipo = t; break

    modalidade = ''
    if re.search(r'1[ºo][\s.]*pra[çc]a', text, re.IGNORECASE):
        modalidade = '1ª Praça'
    elif re.search(r'2[ºo][\s.]*pra[çc]a', text, re.IGNORECASE):
        modalidade = '2ª Praça'
    elif re.search(r'extrajudicial', text, re.IGNORECASE):
        modalidade = 'Leilão Extrajudicial'

    return {
        'ok': True, 'titulo': titulo[:120], 'descricao': desc,
        'foto': foto, 'images': [foto] if foto else [],
        'avaliacao': avaliacao, 'lance': lance, 'incremento': '',
        'data': data_leilao, 'leiloeiro': meta('og:site_name'),
        'area': area, 'cidade': cidade, 'tipo': tipo, 'modalidade': modalidade,
        'edital': edital, 'matricula': matricula,
        'processo': '', 'leilao_num': '', 'autor': '', 'reu': '',
        'vara': '', 'comarca': '', 'url': url,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ROTA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

# Mapa de domínio → função extratora
EXTRACTORS = {
    'grupolance.com.br':       extract_grupolance,
    'freitasleiloeiro.com.br': extract_freitasleiloeiro,
    'portalbayit.com.br':      extract_portalbayit,
}

def detect_platform(soup):
    """Detecta plataformas genéricas pelo HTML antes de usar o fallback."""
    # Plataforma Degrau (Sua Plataforma de Leilão) — usa prefixo dg-
    if soup.find('h1', class_='dg-lote-titulo') or \
       soup.find('meta', attrs={'name': 'plataforma_de_leilão:site'}):
        return extract_portalbayit
    return None

@app.route('/extract')
def extract():
    url = request.args.get('url', '').strip().split('#')[0]  # remove ancora
    if not url:
        return jsonify({'ok': False, 'error': 'URL não informada'}), 400

    # Detectar domínio
    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    domain = m.group(1) if m else ''

    try:
        resp = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True, verify=False)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        html = resp.text
    except Exception as e:
        try:
            html = fetch_with_playwright(url)
        except Exception as e2:
            return jsonify({'ok': False, 'error': f'Não foi possível acessar o site: {e}'}), 502

    soup = BeautifulSoup(html, 'html.parser')

    # Escolher extrator: domínio específico → plataforma detectada → genérico
    extractor = EXTRACTORS.get(domain) or detect_platform(soup) or extract_generic
    result    = extractor(soup, url)
    return jsonify(result)


def fetch_with_playwright(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page(extra_http_headers=HEADERS)
        page.goto(url, wait_until='networkidle', timeout=30000)
        html    = page.content()
        browser.close()
    return html


@app.route('/ping')
def ping():
    return jsonify({'ok': True, 'msg': 'Servidor ativo'})


if __name__ == '__main__':
    print('=' * 52)
    print('  Extrator de Leilão — Douglas Rosa')
    print('  Servidor: http://localhost:5001')
    print('  Deixe esta janela aberta enquanto usar o app')
    print('=' * 52)
    app.run(port=5001, debug=False)
