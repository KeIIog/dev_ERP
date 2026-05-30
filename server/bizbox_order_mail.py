# server/bizbox_order_mail.py
# 발주서 전송용 Bizbox 메일 자동작성 보조 모듈
import os
import time
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# Selenium Chrome is intentionally kept alive after automatic mail composition.
# Without this strong reference, ChromeDriver/WebDriver may be garbage-collected
# after the API returns, and all Bizbox mail compose windows can close a few
# seconds later on some Selenium/Chrome versions.
_ACTIVE_ORDER_MAIL_SESSIONS: List[Dict] = []
_MAX_ACTIVE_ORDER_MAIL_SESSIONS = 20


def _keep_order_mail_session_alive(bot, driver, mail_jobs) -> None:
    try:
        _ACTIVE_ORDER_MAIL_SESSIONS.append({
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'bot': bot,
            'driver': driver,
            'job_count': len(mail_jobs or []),
        })
        if len(_ACTIVE_ORDER_MAIL_SESSIONS) > _MAX_ACTIVE_ORDER_MAIL_SESSIONS:
            # Drop only the reference to the oldest session. Do not call quit().
            # Users may still be reviewing/editing the old mail compose windows.
            del _ACTIVE_ORDER_MAIL_SESSIONS[0:len(_ACTIVE_ORDER_MAIL_SESSIONS) - _MAX_ACTIVE_ORDER_MAIL_SESSIONS]
        logger.info('Bizbox order mail browser session kept alive. active_sessions=%s', len(_ACTIVE_ORDER_MAIL_SESSIONS))
    except Exception:
        logger.exception('Failed to keep Bizbox order mail browser session alive')


def auto_open_order_mail_windows(mail_jobs: List[Dict], user_id: str, user_pw: str) -> dict:
    """Bizbox 메일 작성창을 업체별로 열고 수신자/제목/본문/첨부를 자동 입력한다.
    브라우저 보안 문제를 피하기 위해 서버 PC에서 Selenium Chrome을 직접 실행한다.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from server.bizbox_selenium import BizboxAutomation
    from shared.config import BIZBOX_URL

    driver = None
    try:
        # 결재상신과 동일한 강화 로그인 루틴을 사용한다.
        bot = BizboxAutomation(headless=False)
        if not bot.login(user_id, user_pw):
            msg = bot.last_error or 'Bizbox 로그인 실패'
            if bot.last_debug_files:
                import json
                msg += '\n디버그 파일: ' + json.dumps(bot.last_debug_files, ensure_ascii=False)
            return {'success': False, 'message': msg, 'debug_files': bot.last_debug_files, 'alert': bot.last_alert}
        driver = bot.driver
        main_win = bot.main_window or driver.current_window_handle
        time.sleep(1.5)

        driver.switch_to.default_content()
        try:
            driver.execute_script("onclickTopCustomMenu(200000000,'메일', arguments[0] + '/mail2/?ssoType=GW','mail','','N');", BIZBOX_URL)
        except Exception:
            try:
                mail_btn = driver.find_element(By.ID, 'topMenu200000000')
                driver.execute_script('arguments[0].click();', mail_btn)
            except Exception:
                pass
        time.sleep(2.5)

        ok_count = 0
        for job in mail_jobs or []:
            try:
                driver.switch_to.window(main_win)
                driver.switch_to.default_content()
                _click_mail_write(driver)
                time.sleep(1.5)
                handles = [h for h in driver.window_handles if h != main_win]
                if not handles:
                    logger.warning('메일 작성창이 열리지 않음: %s', job.get('vendor_name'))
                    continue
                mail_win = handles[-1]
                driver.switch_to.window(mail_win)
                time.sleep(1.2)
                _fill_recipient(driver, job.get('to',''))
                _fill_subject(driver, job.get('subject',''))
                _inject_body(driver, job.get('body_html',''))
                _attach_files(driver, job.get('attachments') or [])
                ok_count += 1
            except Exception as e:
                logger.warning('메일 자동작성 실패(%s): %s', job.get('vendor_name'), e)
                try:
                    driver.switch_to.window(main_win)
                except Exception:
                    pass
        _keep_order_mail_session_alive(bot, driver, mail_jobs)
        return {'success': True, 'count': ok_count, 'kept_alive': True, 'active_sessions': len(_ACTIVE_ORDER_MAIL_SESSIONS)}
    except Exception as e:
        logger.exception('Bizbox 메일 자동작성 전체 실패')
        return {'success': False, 'message': str(e)}


def _click_mail_write(driver):
    from selenium.webdriver.common.by import By
    clicked = False
    for frm in driver.find_elements(By.TAG_NAME, 'iframe'):
        try:
            driver.switch_to.default_content(); driver.switch_to.frame(frm)
            btn = driver.find_element(By.CSS_SELECTOR, 'input#btnWrite, input[value="메일쓰기"], button#btnWrite')
            driver.execute_script('arguments[0].click();', btn)
            clicked = True; break
        except Exception:
            continue
    if not clicked:
        driver.switch_to.default_content()
        try:
            btn = driver.find_element(By.CSS_SELECTOR, 'input#btnWrite, input[value="메일쓰기"], button#btnWrite')
            driver.execute_script('arguments[0].click();', btn)
            clicked = True
        except Exception:
            try:
                driver.execute_script("if(typeof writeMail==='function') writeMail('plain');")
                clicked = True
            except Exception:
                pass
    if not clicked:
        raise RuntimeError('메일쓰기 버튼을 찾지 못했습니다.')


def _fill_recipient(driver, email: str) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    email=(email or '').strip()
    if not email: return False
    scripts=[
        """
        const email=arguments[0];
        const setters=(el,value)=>{const proto=Object.getPrototypeOf(el); const desc=Object.getOwnPropertyDescriptor(proto,'value'); if(desc&&desc.set) desc.set.call(el,value); else el.value=value; ['input','change','keyup','blur'].forEach(evt=>el.dispatchEvent(new Event(evt,{bubbles:true})));};
        const wrap=document.querySelector('#pudd_mail_to');
        if(wrap){wrap.click(); const input=wrap.querySelector('input, textarea, [contenteditable="true"]'); if(input){if(input.isContentEditable){input.focus(); input.innerText=email;} else setters(input,email); return true;}}
        return false;
        """,
        """
        const email=arguments[0]; const sel=document.querySelector('select#mail_to');
        if(sel){let opt=Array.from(sel.options).find(o=>(o.value||'').trim()===email||(o.text||'').includes(email)); if(!opt){opt=new Option(email,email,true,true); sel.add(opt);} sel.value=email; ['input','change'].forEach(evt=>sel.dispatchEvent(new Event(evt,{bubbles:true}))); return true;} return false;
        """,
        """
        const email=arguments[0]; const candidates=Array.from(document.querySelectorAll('input[type=text], input:not([type]), textarea, [contenteditable=true]'));
        const target=candidates.find(el=>{const s=[el.id||'',el.name||'',el.className||'',el.placeholder||''].join(' ').toLowerCase(); return /mail|addr|recipient|to|받는/.test(s);});
        if(!target) return false; target.focus(); if(target.isContentEditable){target.innerText=email;} else {target.value=email;} ['input','change','keyup','blur'].forEach(evt=>target.dispatchEvent(new Event(evt,{bubbles:true}))); return true;
        """
    ]
    for sc in scripts:
        try:
            if driver.execute_script(sc, email):
                time.sleep(0.3)
                try: driver.switch_to.active_element.send_keys(Keys.RETURN)
                except Exception: pass
                return True
        except Exception: pass
    for sel in ['#pudd_mail_to input','#pudd_mail_to textarea','#mail_to','input[name*=mail]','input[id*=mail]']:
        try:
            el=driver.find_element(By.CSS_SELECTOR, sel); el.click();
            try: el.clear()
            except Exception: pass
            el.send_keys(email); el.send_keys(Keys.RETURN); return True
        except Exception: pass
    return False


def _fill_subject(driver, subject: str) -> bool:
    from selenium.webdriver.common.by import By
    subject = subject or ''
    for sel in ['#mail_subject','input[name=mail_subject]','input[id*=subject]','input[name*=subject]']:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            try: el.clear()
            except Exception: pass
            el.send_keys(subject)
            return True
        except Exception: pass
    return False


def _inject_body(driver, html: str) -> bool:
    """Bizbox 메일 본문 상단에 HTML을 삽입한다.
    기존 클라이언트 프로그램에서 쓰던 방식처럼 TinyMCE/CKEditor/contenteditable/iframe을 모두 탐색한다.
    """
    from selenium.webdriver.common.by import By
    html = html or ''
    if not html.strip():
        return False

    # 1) 현재 프레임 기준: TinyMCE / CKEditor 우선
    for js in [
        """
        if(typeof tinymce!=='undefined' && tinymce.editors && tinymce.editors.length>0){
          var ed=tinymce.editors[0];
          var cur=ed.getContent();
          ed.setContent(arguments[0]+cur);
          try{ed.fire('change'); ed.fire('keyup');}catch(e){}
          return true;
        }
        return false;
        """,
        """
        if(typeof CKEDITOR!=='undefined'){
          var k=Object.keys(CKEDITOR.instances)[0];
          if(k){var ed=CKEDITOR.instances[k]; var cur=ed.getData(); ed.setData(arguments[0]+cur); try{ed.fire('change');}catch(e){} return true;}
        }
        return false;
        """,
    ]:
        try:
            if driver.execute_script(js, html):
                return True
        except Exception:
            pass

    # 2) JS 재귀 탐색: 현재 document 내부 iframe/contenteditable/textarea
    js_recursive = """
    const html = arguments[0];
    function fire(el){
      ['focus','input','change','keyup','blur'].forEach(evt => {
        try { el.dispatchEvent(new Event(evt, {bubbles:true})); } catch(e) {}
      });
    }
    function setValue(el, html){
      try { el.scrollIntoView({block:'center'}); } catch(e) {}
      try { el.focus(); } catch(e) {}
      if (el.isContentEditable) {
        try { el.innerHTML = html + (el.innerHTML || ''); fire(el); return true; } catch(e) {}
      }
      const tag=(el.tagName||'').toLowerCase();
      if (tag === 'textarea' || tag === 'input') {
        try {
          const proto = Object.getPrototypeOf(el);
          const desc = Object.getOwnPropertyDescriptor(proto, 'value');
          if (desc && desc.set) desc.set.call(el, html + (el.value || ''));
          else el.value = html + (el.value || '');
          fire(el); return true;
        } catch(e) {}
      }
      return false;
    }
    function score(el){
      const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : {width:0,height:0};
      const meta = [el.id||'', el.name||'', el.className||'', el.getAttribute?.('title')||'', el.getAttribute?.('aria-label')||''].join(' ').toLowerCase();
      let s = rect.width * rect.height;
      if (/editor|body|content|write|mail|smart|compose|cke|tox|ir1|iframe/.test(meta)) s += 1000000;
      return s;
    }
    function findAndFill(doc){
      try {
        const body = doc.body;
        if (body && (body.isContentEditable || doc.designMode === 'on')) {
          body.innerHTML = html + (body.innerHTML || ''); fire(body); return true;
        }
      } catch(e) {}
      let candidates=[];
      try { candidates = Array.from(doc.querySelectorAll('[contenteditable="true"], textarea, iframe')); } catch(e) {}
      let best=null, bestScore=-1;
      for(const el of candidates){
        const tag=(el.tagName||'').toLowerCase();
        if(tag==='iframe'){
          try{ const sub=el.contentWindow && el.contentWindow.document; if(sub && findAndFill(sub)) return true; }catch(e){}
          continue;
        }
        const sc=score(el);
        if(sc>bestScore){best=el; bestScore=sc;}
      }
      if(best && setValue(best, html)) return true;
      return false;
    }
    return findAndFill(document);
    """
    try:
        if driver.execute_script(js_recursive, html):
            return True
    except Exception:
        pass

    # 3) Selenium으로 프레임 직접 순회
    def _walk_frames(path=None):
        path = path or []
        try:
            driver.switch_to.default_content()
            for idx in path:
                frames = driver.find_elements(By.TAG_NAME, 'iframe')
                if idx >= len(frames):
                    return False
                driver.switch_to.frame(frames[idx])

            ok = driver.execute_script("""
                const html = arguments[0];
                function fire(el){['input','change','keyup','blur'].forEach(evt=>{try{el.dispatchEvent(new Event(evt,{bubbles:true}));}catch(e){}});}
                if (document.body && (document.body.isContentEditable || document.designMode === 'on')) {
                    document.body.innerHTML = html + (document.body.innerHTML || ''); fire(document.body); return true;
                }
                const els = Array.from(document.querySelectorAll('[contenteditable="true"], textarea, input'));
                if (!els.length) return false;
                const target = els.sort((a,b)=>{
                    const ra=a.getBoundingClientRect(); const rb=b.getBoundingClientRect();
                    return (rb.width*rb.height)-(ra.width*ra.height);
                })[0];
                try{target.focus();}catch(e){}
                if (target.isContentEditable) target.innerHTML = html + (target.innerHTML || '');
                else target.value = html + (target.value || '');
                fire(target); return true;
            """, html)
            if ok:
                driver.switch_to.default_content()
                return True
            subframes = driver.find_elements(By.TAG_NAME, 'iframe')
            for i in range(len(subframes)):
                if _walk_frames(path + [i]):
                    return True
            driver.switch_to.default_content()
            return False
        except Exception:
            try: driver.switch_to.default_content()
            except Exception: pass
            return False

    if _walk_frames([]):
        return True

    # 4) 마지막 폴백: active element에 insertHTML
    try:
        active = driver.switch_to.active_element
        return bool(driver.execute_script("""
            const el=arguments[0], html=arguments[1];
            if(!el) return false;
            try{el.focus();}catch(e){}
            if(el.isContentEditable){try{document.execCommand('insertHTML', false, html); return true;}catch(e){} el.innerHTML=html+(el.innerHTML||''); return true;}
            const tag=(el.tagName||'').toLowerCase();
            if(tag==='textarea'||tag==='input'){el.value=html+(el.value||''); ['input','change','keyup','blur'].forEach(evt=>el.dispatchEvent(new Event(evt,{bubbles:true}))); return true;}
            return false;
        """, active, html))
    except Exception:
        return False

def _attach_files(driver, file_paths) -> bool:
    from selenium.webdriver.common.by import By
    paths=[os.path.abspath(p) for p in (file_paths or []) if p and os.path.exists(p)]
    if not paths: return False
    try: driver.switch_to.default_content()
    except Exception: pass
    for sel in ['button#attach','#attach','.file_add_trigger','span.bl_btnattach']:
        try:
            el=driver.find_element(By.CSS_SELECTOR, sel); driver.execute_script('arguments[0].click();', el); time.sleep(0.3); break
        except Exception: pass
    try:
        driver.execute_script("""document.querySelectorAll('input[type=file]').forEach(function(el){el.style.display='block';el.style.opacity='1';el.style.visibility='visible';el.style.width='420px';el.style.height='28px';el.removeAttribute('disabled');});""")
        inputs=[]
        for sel in ["input#fileupload","input[name='files[]']","input[type='file']"]:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    if el not in inputs: inputs.append(el)
            except Exception: pass
        if not inputs: return False
        inputs[0].send_keys('\n'.join(paths))
        time.sleep(1.5)
        return True
    except Exception:
        return False
