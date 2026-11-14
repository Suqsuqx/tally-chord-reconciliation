"""Static, dependency-free public landing page for Tally."""

DESK_CHAT_URL = "https://chat.tsglabs.dev/c/eEyqFbLfrlZbJsEMBPVfNsOD"

LANDING_PAGE_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f6f8f4">
  <meta name="description" content="Set up your business with Tally Desk, then open a dedicated Tally Shop for your customers.">
  <title>Tally — Your business, in good order</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #153b32;
      --body: #536b63;
      --green: #087c67;
      --green-dark: #056451;
      --mint: #e4f2e9;
      --paper: #f6f8f4;
      --white: #fff;
      --line: #dce7df;
      --gold: #f5c878;
      --shadow: 0 24px 70px rgba(21, 59, 50, .09);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 16px/1.55 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      -webkit-font-smoothing: antialiased;
    }}
    a {{ color: inherit; }}
    a:focus-visible {{ outline: 3px solid var(--gold); outline-offset: 4px; }}
    .shell {{ width: min(1120px, calc(100% - 48px)); margin: 0 auto; }}
    .header {{ height: 82px; display: flex; align-items: center; justify-content: space-between; }}
    .brand {{ display: inline-flex; align-items: center; gap: 10px; text-decoration: none; font-size: 1.24rem; font-weight: 800; letter-spacing: -.05em; }}
    .brand-mark {{ display: grid; place-items: center; width: 36px; height: 36px; border-radius: 12px; background: var(--green); color: white; }}
    .brand-mark svg {{ width: 20px; height: 20px; }}
    .nav {{ display: flex; align-items: center; gap: 30px; font-size: .92rem; font-weight: 650; }}
    .nav a {{ text-decoration: none; }}
    .nav .nav-cta {{ color: var(--green-dark); }}
    .hero {{ display: grid; grid-template-columns: 1.08fr .92fr; align-items: center; gap: clamp(36px, 7vw, 92px); padding: 72px 0 92px; }}
    .eyebrow {{ display: inline-flex; align-items: center; gap: 9px; margin-bottom: 22px; color: var(--green-dark); font-size: .76rem; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; }}
    .eyebrow::before {{ content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 5px var(--mint); }}
    h1 {{ max-width: 640px; margin: 0; font-size: clamp(3rem, 6.6vw, 5.35rem); line-height: .99; letter-spacing: -.075em; font-weight: 760; }}
    .hero-copy {{ max-width: 550px; margin: 25px 0 0; color: var(--body); font-size: clamp(1.03rem, 1.6vw, 1.18rem); line-height: 1.7; }}
    .actions {{ display: flex; align-items: center; gap: 17px; flex-wrap: wrap; margin-top: 31px; }}
    .button {{ display: inline-flex; min-height: 54px; align-items: center; justify-content: center; gap: 12px; padding: 0 21px; border: 1px solid var(--green); border-radius: 13px; background: var(--green); color: white; text-decoration: none; font-weight: 750; box-shadow: 0 10px 24px rgba(8, 124, 103, .16); transition: background .15s ease, transform .15s ease, box-shadow .15s ease; }}
    .button:hover {{ background: var(--green-dark); box-shadow: 0 13px 28px rgba(8, 124, 103, .22); transform: translateY(-1px); }}
    .button-arrow {{ font-size: 1.2rem; line-height: 1; }}
    .private-note {{ display: flex; align-items: center; gap: 9px; color: var(--body); font-size: .87rem; }}
    .private-note svg {{ width: 17px; height: 17px; flex: none; color: var(--green); }}
    .journey {{ position: relative; padding: 29px; overflow: hidden; border: 1px solid #d9e7dc; border-radius: 25px; background: linear-gradient(145deg, #edf5ed, #e7f1e7 65%, #f3f4e9); box-shadow: var(--shadow); }}
    .journey::after {{ content: ""; position: absolute; right: -78px; top: -87px; width: 220px; height: 220px; border: 1px solid rgba(8, 124, 103, .11); border-radius: 50%; box-shadow: 0 0 0 25px rgba(8, 124, 103, .035), 0 0 0 51px rgba(8, 124, 103, .025); }}
    .journey-label {{ position: relative; z-index: 1; margin: 0 0 21px; color: #71857c; font-size: .7rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }}
    .journey-card {{ position: relative; z-index: 1; display: flex; align-items: center; gap: 15px; padding: 17px; border: 1px solid rgba(21, 59, 50, .08); border-radius: 16px; background: rgba(255, 255, 255, .9); }}
    .journey-icon {{ display: grid; width: 42px; height: 42px; flex: none; place-items: center; border-radius: 13px; background: var(--mint); color: var(--green-dark); }}
    .journey-icon svg {{ width: 21px; height: 21px; }}
    .journey-card strong {{ display: block; font-size: .96rem; letter-spacing: -.02em; }}
    .journey-card small {{ display: block; margin-top: 2px; color: var(--body); font-size: .81rem; }}
    .connector {{ position: relative; z-index: 1; height: 34px; margin-left: 38px; border-left: 1px dashed #8bb4a2; }}
    .connector span {{ position: absolute; left: -5px; bottom: -1px; width: 9px; height: 9px; border-right: 1px solid var(--green); border-bottom: 1px solid var(--green); transform: rotate(45deg); }}
    .journey-foot {{ position: relative; z-index: 1; display: flex; align-items: center; gap: 9px; margin: 21px 0 0; color: var(--green-dark); font-size: .81rem; font-weight: 700; }}
    .journey-foot span {{ display: grid; width: 20px; height: 20px; place-items: center; border-radius: 50%; background: rgba(8, 124, 103, .1); font-size: .72rem; }}
    .section {{ padding: 68px 0 76px; border-top: 1px solid var(--line); }}
    .section-heading {{ display: flex; align-items: end; justify-content: space-between; gap: 28px; margin-bottom: 31px; }}
    .section-kicker {{ margin: 0 0 10px; color: var(--green); font-size: .75rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
    h2 {{ max-width: 600px; margin: 0; font-size: clamp(2rem, 4vw, 3rem); line-height: 1.1; letter-spacing: -.06em; }}
    .section-intro {{ max-width: 350px; margin: 0 0 4px; color: var(--body); font-size: .97rem; }}
    .steps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }}
    .step {{ min-height: 196px; padding: 23px 23px 25px; border: 1px solid var(--line); border-radius: 17px; background: var(--white); }}
    .step-number {{ display: grid; width: 31px; height: 31px; margin-bottom: 18px; place-items: center; border-radius: 10px; background: var(--mint); color: var(--green-dark); font-size: .82rem; font-weight: 800; }}
    .step h3 {{ margin: 0; font-size: 1.04rem; letter-spacing: -.025em; }}
    .step p {{ margin: 8px 0 0; color: var(--body); font-size: .89rem; line-height: 1.65; }}
    .ready-strip {{ display: flex; align-items: center; justify-content: space-between; gap: 26px; margin-top: 19px; padding: 22px 25px; border-radius: 17px; background: #e7f1e9; }}
    .ready-strip p {{ max-width: 690px; margin: 0; color: #35594e; font-size: .91rem; }}
    .ready-strip strong {{ color: var(--ink); }}
    .ready-strip a {{ flex: none; color: var(--green-dark); font-size: .9rem; font-weight: 800; text-decoration-thickness: 1px; text-underline-offset: 4px; }}
    .footer {{ display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 22px 0 30px; border-top: 1px solid var(--line); color: #718079; font-size: .78rem; }}
    .footer p {{ margin: 0; }}
    .footer a {{ color: var(--green-dark); font-weight: 750; text-decoration: none; }}
    @media (max-width: 800px) {{
      .hero {{ grid-template-columns: 1fr; gap: 43px; padding: 48px 0 67px; }}
      .journey {{ max-width: 570px; }}
      .section-heading {{ align-items: start; flex-direction: column; gap: 12px; }}
      .section-intro {{ max-width: 600px; }}
    }}
    @media (max-width: 600px) {{
      .shell {{ width: min(100% - 34px, 1120px); }}
      .header {{ height: 69px; }}
      .nav {{ gap: 16px; font-size: .83rem; }}
      .nav a:first-child {{ display: none; }}
      .hero {{ padding: 47px 0 58px; }}
      h1 {{ font-size: clamp(2.85rem, 15vw, 4.4rem); }}
      .hero-copy {{ margin-top: 20px; font-size: 1rem; }}
      .actions {{ align-items: start; flex-direction: column; gap: 15px; }}
      .button {{ width: 100%; }}
      .journey {{ padding: 20px; border-radius: 20px; }}
      .section {{ padding: 54px 0 57px; }}
      .steps {{ grid-template-columns: 1fr; gap: 10px; }}
      .step {{ min-height: auto; padding: 19px; }}
      .step-number {{ margin-bottom: 13px; }}
      .ready-strip {{ align-items: start; flex-direction: column; padding: 19px; }}
      .footer {{ align-items: start; flex-direction: column; gap: 7px; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      html {{ scroll-behavior: auto; }}
      .button {{ transition: none; }}
    }}
  </style>
</head>
<body>
  <header class="shell header">
    <a class="brand" href="/" aria-label="Tally home">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none"><path d="M5 7.5h14M12 7.5v11M8.5 18.5h7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      </span>
      <span>Tally</span>
    </a>
    <nav class="nav" aria-label="Main navigation">
      <a href="#how-it-works">How it works</a>
      <a class="nav-cta" href="{DESK_CHAT_URL}">Get started <span aria-hidden="true">↗</span></a>
    </nav>
  </header>

  <main>
    <section class="shell hero" aria-labelledby="hero-title">
      <div>
        <p class="eyebrow">Business, in good order</p>
        <h1 id="hero-title">A simpler way to run your business.</h1>
        <p class="hero-copy">Set up with Tally Desk in a conversation. When you’re ready, open Tally Shop—a dedicated assistant for your customers and your business.</p>
        <div class="actions">
          <a class="button" href="{DESK_CHAT_URL}">Get started in Tally Desk <span class="button-arrow" aria-hidden="true">→</span></a>
          <span class="private-note">
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 10V7a5 5 0 0 1 10 0v3m-11 0h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            Your Shop stays private until you activate it.
          </span>
        </div>
      </div>

      <aside class="journey" aria-label="How Tally Desk and Tally Shop work together">
        <p class="journey-label">One business. Two helpful experiences.</p>
        <div class="journey-card">
          <span class="journey-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M4 5.5h16v11H9l-5 3v-14Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M8 9h8M8 12.5h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></span>
          <span><strong>Tally Desk</strong><small>Your private business setup and operations</small></span>
        </div>
        <div class="connector" aria-hidden="true"><span></span></div>
        <div class="journey-card">
          <span class="journey-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M4 9h16l-1.5 11h-13L4 9Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="m4 9 2-5h12l2 5M9 13v3m6-3v3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span><strong>Tally Shop</strong><small>A customer-facing assistant for your business</small></span>
        </div>
        <p class="journey-foot"><span aria-hidden="true">✓</span> Never a marketplace of unrelated shops</p>
      </aside>
    </section>

    <section class="section" id="how-it-works" aria-labelledby="steps-title">
      <div class="shell">
        <div class="section-heading">
          <div>
            <p class="section-kicker">From first chat to first order</p>
            <h2 id="steps-title">Start small. Open when you’re ready.</h2>
          </div>
          <p class="section-intro">Tally keeps setup clear and lets you approve business information before it’s saved.</p>
        </div>

        <div class="steps">
          <article class="step">
            <span class="step-number">01</span>
            <h3>Tell Desk your business name</h3>
            <p>Your business is created empty and private. No old shop or catalogue is assumed.</p>
          </article>
          <article class="step">
            <span class="step-number">02</span>
            <h3>Add your catalogue and payment</h3>
            <p>Share details in chat or connect Notion to preview your business information before import.</p>
          </article>
          <article class="step">
            <span class="step-number">03</span>
            <h3>Activate your Tally Shop</h3>
            <p>Once your catalogue and payment method are ready, open the dedicated assistant for your customers.</p>
          </article>
        </div>

        <div class="ready-strip">
          <p><strong>Only the essentials block opening your Shop.</strong> Your catalogue and payment method are required; profile details and policies can be added or updated anytime.</p>
          <a href="{DESK_CHAT_URL}">Start with Tally Desk <span aria-hidden="true">→</span></a>
        </div>
      </div>
    </section>
  </main>

  <footer class="shell footer">
    <p>© 2026 Tally. Built for the people behind every order.</p>
    <p>Ready to set up? <a href="{DESK_CHAT_URL}">Talk to Tally Desk</a></p>
  </footer>
</body>
</html>
"""
