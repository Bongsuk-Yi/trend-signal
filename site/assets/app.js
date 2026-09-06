/* Trend Signal — 복호화 + 렌더링 (브라우저 전용, 서버 없음) */

(() => {
  'use strict';

  const DATA_URL = 'data/latest.enc.json';
  const STORE_KEY = 'ts.pw';

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const link = (href, cls, text) => {
    const a = el('a', cls, text);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  };
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const nf = (n, d = 0) =>
    Number(n).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });

  /* ── 복호화 ─────────────────────────────────────── */

  async function decryptPayload(env, password) {
    const key = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']
    );
    const aesKey = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt: b64(env.salt), iterations: env.iterations, hash: 'SHA-256' },
      key, { name: 'AES-GCM', length: 256 }, false, ['decrypt']
    );
    const plainBuf = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: b64(env.iv) }, aesKey, b64(env.data)
    );

    let bytes = new Uint8Array(plainBuf);
    if (env.compression === 'gzip') {
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
      bytes = new Uint8Array(await new Response(stream).arrayBuffer());
    }
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  /* ── 렌더 ───────────────────────────────────────── */

  function renderBrief(d) {
    const b = d.brief || {};
    const stats = $('brief-stats');
    stats.textContent = '';
    const tiles = [
      ['급상승 키워드', b.trend_count ?? (d.trends || []).length, '개'],
      ['24시간 뉴스', b.news_count_24h ?? 0, '건'],
      ['선행 신호', (b.leading_signals || []).length, '개'],
      ['화제 이슈', (d.clusters || []).length, '건'],
    ];
    for (const [k, v, u] of tiles) {
      const s = el('div', 'stat');
      s.append(el('div', 'k', k));
      const val = el('div', 'v', nf(v));
      val.append(el('span', 'u', u));
      s.append(val);
      stats.append(s);
    }

    const fill = (node, arr) => {
      node.textContent = '';
      if (!arr || !arr.length) { node.append(el('span', 'empty', '해당 없음')); return; }
      arr.forEach((k) => node.append(el('span', 'chip', k)));
    };
    fill($('brief-fresh'), b.fresh_keywords);
    fill($('brief-leading'), b.leading_signals);
  }

  function renderMarket(d) {
    const g = $('market-grid');
    g.textContent = '';
    const list = d.market || [];
    if (!list.length) { g.append(el('p', 'empty', '시장 데이터를 불러오지 못했습니다.')); return; }

    for (const m of list) {
      const c = el('div', 'mkt');
      c.append(el('div', 'name', m.label));
      const dec = m.unit === '원' && m.price > 10000 ? 0 : 2;
      c.append(el('div', 'px', nf(m.price, dec)));
      const dir = m.rate > 0 ? 'up' : m.rate < 0 ? 'down' : 'flat';
      const sign = m.rate > 0 ? '▲' : m.rate < 0 ? '▼' : '–';
      c.append(el('div', 'ch ' + dir,
        `${sign} ${nf(Math.abs(m.change), dec)}  (${m.rate > 0 ? '+' : ''}${nf(m.rate, 2)}%)`));
      g.append(c);
    }
  }

  function renderTrends(d) {
    const g = $('trend-grid');
    g.textContent = '';
    const list = (d.trends || []).slice(0, 24);
    if (!list.length) { g.append(el('p', 'empty', '급상승 데이터가 없습니다.')); return; }

    list.forEach((t, i) => {
      const c = el('div', 'tcard');
      const top = el('div', 'tcard-top');
      top.append(el('span', 'rank', String(i + 1)));
      top.append(el('div', 'kw', t.keyword));
      if (t.traffic && t.traffic !== '-') top.append(el('span', 'tr', t.traffic));
      c.append(top);

      if (t.news && t.news.length) {
        const box = el('div', 'tnews');
        t.news.slice(0, 2).forEach((n) => {
          const a = link(n.url, null, n.title);
          a.append(el('span', 'src', n.source || ''));
          box.append(a);
        });
        c.append(box);
      }
      g.append(c);
    });
  }

  function renderCross(d) {
    const box = $('cross-list');
    box.textContent = '';
    const list = d.cross || [];
    if (!list.length) { box.append(el('p', 'empty', '분석 데이터가 없습니다.')); return; }

    const cls = { '검색만': 'lead', '확산 초기': 'early', '보도 확산': 'wide' };
    const sorted = [...list].sort((a, b) => {
      const rank = { '검색만': 0, '확산 초기': 1, '보도 확산': 2 };
      return (rank[a.status] - rank[b.status]) || (b.traffic_num - a.traffic_num);
    });

    for (const c of sorted) {
      const k = cls[c.status] || '';
      const row = el('div', 'crow ' + k);
      const head = el('div', 'crow-head');
      head.append(el('span', 'kw', c.keyword));
      head.append(el('span', 'badge ' + k, c.status));
      head.append(el('span', 'badge', c.traffic));
      head.append(el('span', 'badge', `기사 ${c.coverage}건`));
      row.append(head);
      row.append(el('p', 'note', c.note));

      if (c.articles && c.articles.length) {
        const links = el('div', 'links');
        c.articles.forEach((a) => links.append(link(a.url, null, `· ${a.title}`)));
        row.append(links);
      }
      box.append(row);
    }
  }

  function renderPersistent(d) {
    const box = $('persistent-list');
    box.textContent = '';
    const list = d.persistent || [];
    if (!list.length) {
      box.append(el('span', 'empty', '누적 데이터가 쌓이면 표시됩니다 (2일 이상 필요).'));
      return;
    }
    list.forEach((p) => {
      const c = el('span', 'chip', p.keyword);
      c.append(el('span', 'n', `${p.days}일`));
      box.append(c);
    });
  }

  function renderClusters(d) {
    const g = $('cluster-grid');
    g.textContent = '';
    const list = d.clusters || [];
    if (!list.length) { g.append(el('p', 'empty', '클러스터가 없습니다.')); return; }

    for (const c of list) {
      const box = el('div', 'cluster');
      const t = el('div', 'topic');
      t.append(el('span', null, c.topic));
      t.append(el('span', 'cnt', `${c.count}건`));
      box.append(t);
      const ul = el('ul');
      c.articles.forEach((a) => {
        const li = el('li');
        li.append(link(a.url, null, a.title));
        ul.append(li);
      });
      box.append(ul);
      g.append(box);
    }
  }

  function renderTimeline(d) {
    const box = $('timeline-list');
    box.textContent = '';
    const list = d.timeline || [];
    if (!list.length) { box.append(el('p', 'empty', '타임라인 데이터가 없습니다.')); return; }

    for (const row of list) {
      const r = el('div', 'tl-row');
      const h = el('div', 'tl-hour', String(row.hour).padStart(2, '0') + ':00');
      h.append(el('span', 'c', `${row.count}건`));
      r.append(h);
      const items = el('div', 'tl-items');
      row.items.forEach((it) => {
        const a = link(it.url, null, it.title);
        a.append(el('span', 'src', `${it.source} · ${it.time}`));
        items.append(a);
      });
      r.append(items);
      box.append(r);
    }
  }

  function renderRealEstate(d) {
    const box = $('re-body');
    box.textContent = '';
    const re = d.realestate;

    if (!re) {
      const n = el('div', 'notice');
      n.append(document.createTextNode('부동산 실거래는 공공데이터포털 서비스키가 필요합니다. '));
      n.append(el('code', null, 'data.go.kr'));
      n.append(document.createTextNode(' 에서 "아파트 매매 실거래가 상세 자료" 활용신청 후, 발급받은 키를 GitHub 리포지토리 Secrets 에 '));
      n.append(el('code', null, 'DATA_GO_KR_KEY'));
      n.append(document.createTextNode(' 이름으로 등록하면 자동으로 채워집니다.'));
      box.append(n);
      return;
    }

    if (re.unreachable) {
      const n = el('div', 'notice');
      n.append(document.createTextNode(
        '국토교통부 실거래가 API(data.go.kr)가 이 사이트를 빌드하는 GitHub 서버에서 차단되어 있습니다. ' +
        '한국 IP에서는 정상 응답하므로 서비스키 문제가 아니라 접속 지역 제한입니다. ' +
        '한국에서 실행되는 러너로 수집하면 해결됩니다.'));
      box.append(n);
      return;
    }

    const sum = el('div', 'stats');
    const tiles = [
      ['이번 달 거래', nf(re.total_count || 0), '건'],
      ['거래 있는 지역', nf(re.active_count || 0), `/ ${nf(re.region_count || 0)}`],
      ['평균 거래가', nf(Math.round((re.avg_amount || 0) / 10000), 1), '억'],
    ];
    for (const [k, v, u] of tiles) {
      const s = el('div', 'stat');
      s.append(el('div', 'k', k));
      const val = el('div', 'v', v);
      val.append(el('span', 'u', u));
      s.append(val);
      sum.append(s);
    }
    box.append(sum);

    const g = el('div', 're-grid');
    for (const r of re.regions || []) {
      const c = el('div', 're');
      c.append(el('div', 'rname', r.name));
      const st = el('div', 'rstat');
      const a = el('div', null, '이번 달 거래');
      a.append(el('b', null, `${nf(r.count)}건`));
      st.append(a);
      if (r.avg_amount) {
        const b = el('div', null, '평균가');
        b.append(el('b', null, `${nf(Math.round(r.avg_amount / 10000), 1)}억`));
        st.append(b);
      }
      c.append(st);

      if (r.recent && r.recent.length) {
        const ul = el('ul');
        r.recent.forEach((x) => {
          const li = el('li');
          li.append(el('span', null, `${x.apt} ${x.area ? x.area.toFixed(0) + '㎡' : ''}`));
          li.append(el('span', null, `${nf(Math.round(x.amount / 10000), 1)}억`));
          ul.append(li);
        });
        c.append(ul);
      }
      g.append(c);
    }
    box.append(g);
  }

  function renderSources(d) {
    const g = $('src-grid');
    g.textContent = '';
    const labels = {
      google_trends: 'Google Trends',
      news: '뉴스 RSS',
      market: '시장지표',
      realestate: '부동산 실거래',
    };
    const src = d.sources || {};
    for (const [key, label] of Object.entries(labels)) {
      const s = src[key] || {};
      const row = el('div', 'srchealth');
      const state = s.ok === true ? 'ok' : s.ok === false ? 'bad' : 'off';
      row.append(el('span', 'led ' + state));
      row.append(el('span', 'sname', label));
      let info = '—';
      if (s.count != null) info = `${s.count}건`;
      else if (s.ok === true) info = '정상';
      else if (s.ok === false) info = '실패';
      row.append(el('span', 'sinfo', info));
      g.append(row);
    }
  }

  function render(d) {
    renderBrief(d);
    renderMarket(d);
    renderTrends(d);
    renderCross(d);
    renderPersistent(d);
    renderClusters(d);
    renderTimeline(d);
    renderRealEstate(d);
    renderSources(d);

    const label = (d.brief && d.brief.generated_label) || d.generated_at || '';
    $('updated').textContent = '갱신 ' + label;
    $('foot-meta').textContent = `generated ${d.generated_at || ''} · payload v${d.version || 1}`;
    document.title = 'Trend Signal · ' + label;
  }

  /* ── 부팅 ───────────────────────────────────────── */

  let envelope = null;

  async function loadEnvelope() {
    const res = await fetch(DATA_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error(`데이터 파일을 찾을 수 없습니다 (HTTP ${res.status}).`);
    return res.json();
  }

  async function unlock(password, remember) {
    const err = $('gate-err');
    const btn = $('unlock');
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = '복호화 중…';

    try {
      if (!envelope) envelope = await loadEnvelope();
      const data = await decryptPayload(envelope, password);

      if (remember) {
        try { localStorage.setItem(STORE_KEY, password); } catch (_) { /* ignore */ }
      } else {
        try { localStorage.removeItem(STORE_KEY); } catch (_) { /* ignore */ }
      }

      render(data);
      $('gate').hidden = true;
      $('app').hidden = false;
    } catch (e) {
      try { localStorage.removeItem(STORE_KEY); } catch (_) { /* ignore */ }
      err.textContent = /찾을 수 없|HTTP/.test(e.message)
        ? e.message
        : '비밀번호가 올바르지 않습니다.';
      err.hidden = false;
      $('pw').value = '';
      $('pw').focus();
    } finally {
      btn.disabled = false;
      btn.textContent = '열기';
    }
  }

  $('gate-form').addEventListener('submit', (e) => {
    e.preventDefault();
    unlock($('pw').value, $('remember').checked);
  });

  $('lock').addEventListener('click', () => {
    try { localStorage.removeItem(STORE_KEY); } catch (_) { /* ignore */ }
    location.reload();
  });

  // 저장된 비밀번호가 있으면 자동 해제
  (async () => {
    let saved = null;
    try { saved = localStorage.getItem(STORE_KEY); } catch (_) { /* ignore */ }
    if (saved) {
      $('pw').value = saved;
      await unlock(saved, true);
      if (!$('app').hidden) return;
    }
    $('pw').focus();
  })();
})();
