# server/bizbox_selenium.py
# v1.0 기반 injection 방식 + 템플릿 HTML 바꿔치기

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import logging, time, os, sys, json, traceback, tempfile, shutil, subprocess

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.config import BIZBOX_URL, BIZBOX_LOGIN_ID, BIZBOX_LOGIN_PW
import re

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "bizbox_purchase_template.html")
logger = logging.getLogger(__name__)

# 클라이언트 에이전트에서 실행될 때도 원인 추적이 가능하도록 파일 로그를 강제 활성화한다.
def _setup_bizbox_file_logger():
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "bizbox_selenium.log")
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        if not any(getattr(h, "baseFilename", "") == log_path for h in root_logger.handlers):
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setLevel(logging.INFO)
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            root_logger.addHandler(fh)
    except Exception:
        pass


_setup_bizbox_file_logger()


class BizboxAutomation:
    def __init__(self, headless=False):
        self.headless = headless
        self.driver = self.wait = self.main_window = self.popup_window = None
        self.last_error = ""
        self.last_alert = ""
        self.last_debug_files = {}

    def _log_dir(self):
        try:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            os.makedirs(log_dir, exist_ok=True)
            return log_dir
        except Exception:
            return os.getcwd()

    def _find_chrome_binary(self):
        """Windows 클라이언트 PC에서 Chrome 실행 파일을 최대한 명시적으로 찾는다."""
        candidates = []
        env_bin = os.environ.get("CHROME_BIN") or os.environ.get("GOOGLE_CHROME_BIN")
        if env_bin:
            candidates.append(env_bin)
        for env_name in ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"]:
            root = os.environ.get(env_name)
            if not root:
                continue
            candidates.extend([
                os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(root, "Chromium", "Application", "chrome.exe"),
            ])
        for c in candidates:
            try:
                if c and os.path.exists(c):
                    return c
            except Exception:
                pass
        return ""

    def _chrome_version_text(self, chrome_bin=""):
        try:
            if chrome_bin and os.path.exists(chrome_bin):
                p = subprocess.run([chrome_bin, "--version"], capture_output=True, text=True, timeout=5)
                return (p.stdout or p.stderr or "").strip()
        except Exception as e:
            return f"chrome version check failed: {e}"
        return ""

    def _make_chrome_options(self, profile_dir, debug_mode="port"):
        opts = webdriver.ChromeOptions()
        chrome_bin = self._find_chrome_binary()
        if chrome_bin:
            opts.binary_location = chrome_bin
        if self.headless:
            opts.add_argument("--headless=new")
        # ChromeDriver가 기본 프로필/기존 실행 중인 Chrome과 충돌하지 않도록 전용 임시 프로필을 강제한다.
        opts.add_argument(f"--user-data-dir={profile_dir}")
        if debug_mode == "pipe":
            opts.add_argument("--remote-debugging-pipe")
        else:
            opts.add_argument("--remote-debugging-port=0")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-component-extensions-with-background-pages")
        opts.add_argument("--disable-background-networking")
        opts.add_argument("--disable-sync")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-infobars")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--allow-running-insecure-content")
        opts.add_argument("--remote-allow-origins=*")
        opts.add_argument("--window-size=1920,1080")
        try:
            opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            opts.add_experimental_option("useAutomationExtension", False)
            # Keep Bizbox compose windows open even after the Selenium command that
            # created them returns. This prevents the browser from closing when the
            # driver/service object is released by Python GC.
            opts.add_experimental_option("detach", True)
        except Exception:
            pass
        try:
            opts.add_experimental_option("prefs", {
                "profile.default_content_setting_values.notifications": 2,
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
            })
        except Exception:
            pass
        return opts

    def _make_chrome_service(self, driver_path=None, log_path=None):
        kwargs = {}
        if driver_path:
            kwargs["executable_path"] = driver_path
        # Selenium 버전별 Service 인자 차이를 흡수한다.
        try:
            if log_path:
                kwargs["service_args"] = ["--verbose"]
                kwargs["log_output"] = log_path
            return Service(**kwargs)
        except TypeError:
            kwargs.pop("service_args", None)
            kwargs.pop("log_output", None)
            return Service(**kwargs)

    def _save_driver_launch_failure(self, errors, chrome_bin=""):
        try:
            log_dir = self._log_dir()
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(log_dir, f"chrome_driver_launch_failed_{ts}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("Chrome/ChromeDriver launch failed\n")
                f.write("chrome_bin=" + str(chrome_bin or self._find_chrome_binary()) + "\n")
                f.write("chrome_version=" + str(self._chrome_version_text(chrome_bin or self._find_chrome_binary())) + "\n")
                f.write("python=" + sys.executable + "\n")
                f.write("cwd=" + os.getcwd() + "\n")
                f.write("\n--- attempts ---\n")
                for e in errors:
                    f.write(str(e) + "\n\n")
            self.last_debug_files = {"driver_launch": path}
            logger.error(f"ChromeDriver launch failure saved: {path}")
            return path
        except Exception:
            return ""

    def _init_driver(self):
        """Chrome 실행 안정화 버전.

        기존 오류는 로그인 입력 전에 ChromeDriver 세션 생성 단계에서 Chrome이 바로 종료된 상태였다.
        그래서 기본 프로필 충돌/DevToolsActivePort/드라이버 매칭 문제를 피하도록
        1) 전용 임시 user-data-dir,
        2) Selenium Manager 우선,
        3) webdriver-manager 폴백,
        4) port/pipe 디버깅 모드 폴백,
        5) chromedriver verbose log 저장
        순서로 재시도한다.
        """
        log_dir = self._log_dir()
        try:
            # 이전 실패로 남은 chromedriver만 정리한다. 사용자가 열어 둔 chrome.exe는 건드리지 않는다.
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass

        chrome_bin = self._find_chrome_binary()
        chrome_ver = self._chrome_version_text(chrome_bin)
        logger.info(f"Chrome launch prepare. chrome_bin={chrome_bin or '(auto)'}, version={chrome_ver or '(unknown)'}")

        attempts = []
        errors = []
        # Selenium Manager는 설치된 Chrome에 맞는 드라이버를 자동 매칭하므로 먼저 사용한다.
        for debug_mode in ["port", "pipe"]:
            attempts.append((f"selenium-manager/{debug_mode}", None, debug_mode))
        # webdriver-manager 캐시/다운로드도 폴백으로 남긴다.
        try:
            wm_path = ChromeDriverManager().install()
            for debug_mode in ["port", "pipe"]:
                attempts.append((f"webdriver-manager/{debug_mode}", wm_path, debug_mode))
        except Exception as e:
            errors.append("webdriver-manager prepare failed: " + repr(e))

        for label, driver_path, debug_mode in attempts:
            profile_dir = tempfile.mkdtemp(prefix="deverp_chrome_profile_")
            chromedriver_log = os.path.join(log_dir, f"chromedriver_{time.strftime('%Y%m%d_%H%M%S')}_{label.replace('/', '_')}.log")
            try:
                logger.info(f"ChromeDriver attempt: {label}, driver_path={driver_path or '(selenium-manager)'}, profile={profile_dir}, log={chromedriver_log}")
                opts = self._make_chrome_options(profile_dir, debug_mode=debug_mode)
                service = self._make_chrome_service(driver_path=driver_path, log_path=chromedriver_log)
                self.driver = webdriver.Chrome(service=service, options=opts)
                self.wait = WebDriverWait(self.driver, 20)
                try:
                    self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                    })
                except Exception:
                    pass
                logger.info(f"✅ ChromeDriver session created by {label}")
                return
            except Exception as e:
                tb = traceback.format_exc()
                errors.append(f"[{label}] {repr(e)}\n{tb}\nchromedriver_log={chromedriver_log}\nprofile_dir={profile_dir}")
                logger.error(f"ChromeDriver attempt failed: {label}: {e}")
                try:
                    if self.driver:
                        self.driver.quit()
                except Exception:
                    pass
                self.driver = None
                self.wait = None
                # 실패한 임시 프로필은 잠금이 풀렸을 때만 삭제된다. 삭제 실패는 로그 보존을 위해 무시한다.
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except Exception:
                    pass
                time.sleep(0.5)

        debug_file = self._save_driver_launch_failure(errors, chrome_bin)
        joined = "\n".join(errors[-3:])
        self.last_error = (
            "Chrome/ChromeDriver 세션 생성 실패. Bizbox 로그인 전에 Chrome이 종료되었습니다. "
            "C:\\DevERP_Client_Agent\\logs 의 chrome_driver_launch_failed_*.txt 및 chromedriver_*.log를 확인하세요."
        )
        if debug_file:
            self.last_error += f" debug={debug_file}"
        raise RuntimeError(self.last_error + "\n" + joined[:3000])

    # ── v1.0 그대로: 팝업 전환 ──────────────────────
    def _switch_to_popup(self):
        self.main_window = self.driver.current_window_handle
        for _ in range(40):
            for h in self.driver.window_handles:
                if h != self.main_window:
                    self.driver.switch_to.window(h)
                    self.popup_window = h
                    logger.info(f"팝업 전환 성공: {self.driver.current_url}")
                    return True
            time.sleep(0.25)
        return False

    # ── v1.0 그대로: iframe 진입 ────────────────────
    def _switch_to_frame(self, candidates=None):
        self.driver.switch_to.default_content()
        time.sleep(0.2)
        if candidates is None:
            candidates = ["mainFrame","contentFrame","contentsFrame",
                          "contents","content","main","gwFrame"]
        for cid in candidates:
            for attr in ["id","name"]:
                try:
                    f = self.driver.find_element(By.XPATH, f"//iframe[@{attr}='{cid}']")
                    self.driver.switch_to.frame(f)
                    return True
                except: pass
        try:
            frames = self.driver.find_elements(By.TAG_NAME, "iframe")
            for f in frames:
                src = f.get_attribute("src") or ""
                if any(k in src for k in ["gw","approval","eap","main","doc"]):
                    self.driver.switch_to.frame(f)
                    return True
            if frames:
                self.driver.switch_to.frame(frames[0])
                return True
        except: pass
        return True

    def _switch_to_main(self):
        if self.main_window:
            self.driver.switch_to.window(self.main_window)

    # ── 로그인 진단/탐색 유틸 ─────────────────────────
    def _safe_current_url(self):
        try:
            return self.driver.current_url or ""
        except Exception:
            return ""

    def _safe_title(self):
        try:
            return self.driver.title or ""
        except Exception:
            return ""

    def _wait_ready(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.driver.execute_script("return document.readyState") in ("interactive", "complete"):
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def _save_debug_artifact(self, prefix="bizbox_debug"):
        """로그인/화면 전환 실패 시 원인 확인용 스크린샷과 HTML을 logs 폴더에 남긴다."""
        saved = {}
        try:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            os.makedirs(log_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            png = os.path.join(log_dir, f"{prefix}_{ts}.png")
            html = os.path.join(log_dir, f"{prefix}_{ts}.html")
            meta = os.path.join(log_dir, f"{prefix}_{ts}.txt")
            try:
                self.driver.save_screenshot(png)
                saved["screenshot"] = png
            except Exception:
                pass
            try:
                with open(html, "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source or "")
                saved["html"] = html
            except Exception:
                pass
            try:
                with open(meta, "w", encoding="utf-8") as f:
                    f.write("url=" + self._safe_current_url() + "\n")
                    f.write("title=" + self._safe_title() + "\n")
                    f.write("last_error=" + str(self.last_error) + "\n")
                    f.write("last_alert=" + str(self.last_alert) + "\n")
                saved["meta"] = meta
            except Exception:
                pass
            self.last_debug_files = saved
            logger.error(f"Bizbox debug saved: {saved}")
        except Exception:
            pass
        return saved

    def _element_usable(self, el):
        try:
            return bool(el and el.is_displayed() and el.is_enabled())
        except Exception:
            return bool(el)

    def _find_first_in_current(self, candidates):
        for by, sel in candidates:
            try:
                els = self.driver.find_elements(by, sel)
            except Exception:
                continue
            for el in els:
                if self._element_usable(el):
                    return el
        return None

    def _with_value(self, el, value):
        try:
            el.click()
        except Exception:
            pass
        try:
            el.clear()
        except Exception:
            pass
        try:
            el.send_keys(value)
        except Exception:
            pass
        try:
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));"
                "arguments[0].dispatchEvent(new KeyboardEvent('keyup', {bubbles:true}));",
                el, value)
        except Exception:
            pass

    def _find_login_fields_here(self):
        user_candidates = [
            (By.ID, "userId"), (By.NAME, "userId"),
            (By.ID, "loginId"), (By.NAME, "loginId"),
            (By.ID, "id"), (By.NAME, "id"),
            (By.ID, "uid"), (By.NAME, "uid"),
            (By.CSS_SELECTOR, "input#userId"),
            (By.CSS_SELECTOR, "input[name='userId']"),
            (By.CSS_SELECTOR, "input[id*='user' i]"),
            (By.CSS_SELECTOR, "input[name*='user' i]"),
            (By.CSS_SELECTOR, "input[id*='login' i]"),
            (By.CSS_SELECTOR, "input[name*='login' i]"),
            (By.CSS_SELECTOR, "input[type='text']"),
        ]
        pw_candidates = [
            (By.ID, "userPw"), (By.NAME, "userPw"),
            (By.ID, "password"), (By.NAME, "password"),
            (By.ID, "passwd"), (By.NAME, "passwd"),
            (By.ID, "pwd"), (By.NAME, "pwd"),
            (By.CSS_SELECTOR, "input#userPw"),
            (By.CSS_SELECTOR, "input[name='userPw']"),
            (By.CSS_SELECTOR, "input[id*='pw' i]"),
            (By.CSS_SELECTOR, "input[name*='pw' i]"),
            (By.CSS_SELECTOR, "input[id*='pass' i]"),
            (By.CSS_SELECTOR, "input[name*='pass' i]"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ]
        u = self._find_first_in_current(user_candidates)
        p = self._find_first_in_current(pw_candidates)
        if u and p:
            return u, p
        return None, None

    def _find_login_fields_recursive(self, depth=0, max_depth=4):
        u, p = self._find_login_fields_here()
        if u and p:
            return u, p
        if depth >= max_depth:
            return None, None
        try:
            frames = self.driver.find_elements(By.TAG_NAME, "iframe") + self.driver.find_elements(By.TAG_NAME, "frame")
        except Exception:
            frames = []
        for frame in frames:
            try:
                self.driver.switch_to.frame(frame)
                u, p = self._find_login_fields_recursive(depth + 1, max_depth)
                if u and p:
                    return u, p
            except Exception:
                pass
            try:
                self.driver.switch_to.parent_frame()
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
        return None, None

    def _click_login_button(self, pw_el=None):
        candidates = [
            (By.CLASS_NAME, "login_submit"),
            (By.CSS_SELECTOR, ".login_submit"),
            (By.ID, "login_submit"),
            (By.ID, "loginBtn"),
            (By.ID, "btnLogin"),
            (By.ID, "btn_login"),
            (By.NAME, "login_submit"),
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.CSS_SELECTOR, "button[id*='login' i]"),
            (By.CSS_SELECTOR, "input[id*='login' i]"),
            (By.CSS_SELECTOR, "a[id*='login' i]"),
            (By.CSS_SELECTOR, "button[class*='login' i]"),
            (By.CSS_SELECTOR, "input[class*='login' i]"),
            (By.CSS_SELECTOR, "a[class*='login' i]"),
            (By.XPATH, "//*[self::a or self::button or self::input][contains(normalize-space(.),'로그인') or contains(@value,'로그인') or contains(@title,'로그인') or contains(@alt,'로그인')]"),
            (By.XPATH, "//*[self::a or self::button or self::input][contains(translate(@onclick,'LOGIN','login'),'login')]")
        ]
        btn = self._find_first_in_current(candidates)
        if btn:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            except Exception:
                pass
            try:
                self.driver.execute_script("arguments[0].click();", btn)
                return True
            except Exception:
                try:
                    btn.click()
                    return True
                except Exception:
                    pass
        # Bizbox 구버전에서 쓰던 JS 함수명 후보를 직접 호출한다.
        for js in [
            "if (typeof fn_login === 'function') { fn_login(); return true; } return false;",
            "if (typeof login === 'function') { login(); return true; } return false;",
            "if (typeof actionLogin === 'function') { actionLogin(); return true; } return false;",
            "if (typeof goLogin === 'function') { goLogin(); return true; } return false;",
            "if (typeof checkLogin === 'function') { checkLogin(); return true; } return false;",
        ]:
            try:
                if self.driver.execute_script(js):
                    return True
            except Exception:
                pass
        if pw_el is not None:
            try:
                pw_el.send_keys(Keys.ENTER)
                return True
            except Exception:
                pass
        return False

    def _try_accept_alert(self):
        try:
            alert = self.driver.switch_to.alert
            text = alert.text or ""
            self.last_alert = text
            logger.error(f"Bizbox alert: {text}")
            try:
                alert.accept()
            except Exception:
                pass
            return text
        except Exception:
            return ""

    def _page_text_current(self):
        try:
            return self.driver.execute_script("return (document.body && document.body.innerText) ? document.body.innerText : ''; ") or ""
        except Exception:
            return ""

    def _collect_error_text_recursive(self, depth=0, max_depth=3):
        keywords = ["실패", "오류", "error", "invalid", "비밀번호", "아이디", "인증", "잠금", "만료"]
        texts = []
        txt = self._page_text_current()
        if txt:
            for line in [x.strip() for x in txt.splitlines() if x.strip()]:
                low = line.lower()
                if any(k.lower() in low for k in keywords):
                    texts.append(line[:200])
        if depth >= max_depth:
            return texts[:10]
        try:
            frames = self.driver.find_elements(By.TAG_NAME, "iframe") + self.driver.find_elements(By.TAG_NAME, "frame")
        except Exception:
            frames = []
        for frame in frames:
            try:
                self.driver.switch_to.frame(frame)
                texts.extend(self._collect_error_text_recursive(depth + 1, max_depth))
            except Exception:
                pass
            try:
                self.driver.switch_to.parent_frame()
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
        return texts[:10]

    def _has_logged_in_dom_current(self):
        checks = [
            (By.ID, "topMenu2000000000"),
            (By.ID, "topMenu200000000"),
            (By.CSS_SELECTOR, "[id^='topMenu']"),
            (By.XPATH, "//*[contains(text(),'결재양식')]"),
            (By.XPATH, "//*[contains(text(),'전자결재')]"),
            (By.XPATH, "//*[contains(text(),'메일')]"),
            (By.XPATH, "//*[contains(text(),'로그아웃')]"),
        ]
        for by, sel in checks:
            try:
                if self.driver.find_elements(by, sel):
                    return True
            except Exception:
                pass
        return False

    def _has_logged_in_dom_recursive(self, depth=0, max_depth=4):
        if self._has_logged_in_dom_current():
            return True
        if depth >= max_depth:
            return False
        try:
            frames = self.driver.find_elements(By.TAG_NAME, "iframe") + self.driver.find_elements(By.TAG_NAME, "frame")
        except Exception:
            frames = []
        for frame in frames:
            try:
                self.driver.switch_to.frame(frame)
                if self._has_logged_in_dom_recursive(depth + 1, max_depth):
                    return True
            except Exception:
                pass
            try:
                self.driver.switch_to.parent_frame()
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
        return False

    def _is_logged_in(self):
        """Bizbox 로그인 성공 여부를 URL 문자열 하나로만 판단하지 않는다."""
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        if self._has_logged_in_dom_recursive():
            return True
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        try:
            url = (self.driver.current_url or "").lower()
            title = (self.driver.title or "").lower()
            # 명확히 로그인 페이지가 아니고, Bizbox/GW 메인 URL로 이동한 경우만 성공 후보로 본다.
            if ("/gw/" in url or "/mail" in url or "bizbox" in title) and not any(x in url for x in ["egovloginusr", "/login", "uat/uia"]):
                return True
        except Exception:
            pass
        return False

    def login(self, uid=None, upw=None):
        uid = (uid or BIZBOX_LOGIN_ID or "").strip()
        upw = (upw or BIZBOX_LOGIN_PW or "")
        self.last_error = ""
        self.last_alert = ""
        self.last_debug_files = {}
        if not uid or not upw:
            self.last_error = "Bizbox 아이디/비밀번호가 비어 있습니다. 웹 설정 > 계정정보를 다시 저장하세요."
            logger.error(self.last_error)
            return False
        try:
            self._init_driver()
            login_url = f"{BIZBOX_URL.rstrip('/')}/gw/uat/uia/egovLoginUsr.do"
            logger.info(f"Bizbox login open: {login_url}, uid={uid[:2]}***")
            self.driver.get(login_url)
            self._wait_ready(15)
            time.sleep(0.8)

            # 이미 세션이 살아있거나 SSO로 메인화면에 진입한 경우
            if self._is_logged_in():
                self.driver.switch_to.default_content()
                self.main_window = self.driver.current_window_handle
                logger.info("✅ 로그인 성공(기존 세션/SSO)")
                return True

            u = p = None
            end = time.time() + 20
            while time.time() < end and not (u and p):
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
                u, p = self._find_login_fields_recursive()
                if u and p:
                    break
                time.sleep(0.3)
            if not (u and p):
                self.last_error = "Bizbox 로그인 입력칸(userId/userPw)을 찾지 못했습니다. 로그인 화면 구조가 변경되었거나 보안/팝업 화면에 막혔을 수 있습니다."
                self._save_debug_artifact("bizbox_login_fields_not_found")
                logger.error(self.last_error)
                return False

            self._with_value(u, uid)
            self._with_value(p, upw)
            time.sleep(0.2)

            clicked = self._click_login_button(p)
            if not clicked:
                self.last_error = "Bizbox 로그인 버튼을 찾지 못했습니다."
                self._save_debug_artifact("bizbox_login_button_not_found")
                logger.error(self.last_error)
                return False

            # URL만 보지 말고 메뉴/프레임/알림/페이지 오류 문구까지 함께 확인
            first_error_text = ""
            for _ in range(75):
                alert_text = self._try_accept_alert()
                if alert_text and not first_error_text:
                    first_error_text = alert_text
                try:
                    if self._is_logged_in():
                        self.driver.switch_to.default_content()
                        self.main_window = self.driver.current_window_handle
                        logger.info("✅ 로그인 성공")
                        return True
                except Exception:
                    pass
                try:
                    self.driver.switch_to.default_content()
                    errors = self._collect_error_text_recursive()
                    if errors and not first_error_text:
                        first_error_text = " / ".join(dict.fromkeys(errors))
                except Exception:
                    pass
                time.sleep(0.5)

            url = self._safe_current_url()
            title = self._safe_title()
            detail = first_error_text or self.last_alert or "로그인 후 Bizbox 메인/전자결재 화면으로 전환되지 않았습니다."
            self.last_error = f"Bizbox 로그인 실패: {detail} (url={url}, title={title})"
            self._save_debug_artifact("bizbox_login_failed")
            logger.error(self.last_error)
            return False
        except Exception as e:
            self.last_error = f"Bizbox 로그인 예외: {e}"
            logger.error(self.last_error)
            try:
                logger.error(traceback.format_exc())
            except Exception:
                pass
            self._save_debug_artifact("bizbox_login_exception")
            return False

    # ── v1.0 그대로: 팝업 열기 + iframe 진입 ─────────
    def navigate_to_purchase_form(self):
        try:
            self._switch_to_main()
            self.driver.switch_to.default_content()
            self.driver.execute_script(
                "arguments[0].click();",
                self.wait.until(EC.element_to_be_clickable((By.ID, "topMenu2000000000"))))
            time.sleep(0.2)

            self._switch_to_frame()
            time.sleep(0.2)

            try:
                el = self.wait.until(EC.element_to_be_clickable((By.ID, "2001010000_anchor")))
            except:
                el = self.wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//*[contains(text(),'결재양식')]")))
            self.driver.execute_script("arguments[0].click();", el)
            time.sleep(0.8)

            try:
                el = WebDriverWait(self.driver, 3).until(EC.element_to_be_clickable(
                    (By.XPATH, "//*[contains(text(),'정부과제')]")))
                self.driver.execute_script("arguments[0].click();", el)
                time.sleep(0.2)
            except: pass

            self.driver.execute_script(
                "arguments[0].click();",
                self.wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[contains(text(),'구매의뢰서(정부과제용)')]"))))
            time.sleep(0.3)

            if not self._switch_to_popup():
                return False

            # 팝업 후 default_content 유지 (제목 input은 default_content에 있음)
            self.driver.switch_to.default_content()
            time.sleep(0.3)
            logger.info("✅ 팝업 진입 완료 (default_content)")
            return True
        except Exception as e:
            logger.error(f"양식 이동 실패: {e}", exc_info=True)
            return False

    # ── 메인 업로드 ──────────────────────────────────
    def upload_purchase_request(self, data):
        result = {"success": False, "bizbox_no": None, "message": ""}
        try:
            if not self.navigate_to_purchase_form():
                result["message"] = "양식 이동 실패"
                return result

            time.sleep(0.5)

            # 1. 제목: default_content에서 입력 (v2.9 방식)
            title = self._make_title(data)
            self.driver.switch_to.default_content()
            for eid in ["txtTitle", "docTitle", "title"]:
                try:
                    el = WebDriverWait(self.driver, 4).until(
                        EC.presence_of_element_located((By.ID, eid)))
                    el.clear(); el.send_keys(title)
                    self.driver.execute_script(
                        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", el)
                    logger.info(f"✅ 제목 입력 (#{eid}): {title[:50]}")
                    break
                except: pass

            # 2. HTML 주입: iframe 진입 후 v1.0 방식으로 주입
            self._switch_to_frame()   # ← HTML탭/textarea는 iframe 안에 있음
            time.sleep(0.3)
            editor_html = self._build_complete_html(data)
            self._inject_html(editor_html)

            # 3. 파일 첨부
            raw = data.get("attach_files") or "[]"
            files = raw if isinstance(raw, list) else json.loads(raw)
            if files:
                self._attach_files(files)

            result["success"] = True
            result["message"] = (
                "✅ 자동 입력 완료!\n\nBizbox 화면에서 내용 확인 후\n"
                "결재라인 설정하고 상신해 주세요.")
            logger.info("✅ Bizbox 완료")

        except Exception as e:
            result["message"] = str(e)
            logger.error(f"실패: {e}", exc_info=True)
        return result

    # ── v1.0 핵심 injection (그대로 유지) ────────────
    def _inject_html(self, editor_html):
        """
        v1.0과 동일한 방식:
        1. HTML보기 탭 클릭 (text()= 정확 매칭)
        2. offsetParent !== null 인 textarea 찾아서 .value 설정
        3. 편집보기 클릭
        """
        filled = False

        # HTML보기 탭 찾기 (v1.0과 동일한 XPath 순서)
        for xpath in [
            "//a[text()='HTML보기']",
            "//span[text()='HTML보기']",
            "//*[contains(@class,'tab') and contains(.,'HTML보기')]",
            "//*[@id and contains(.,'HTML보기')]",
        ]:
            try:
                tab = self.driver.find_element(By.XPATH, xpath)
                self.driver.execute_script("arguments[0].click();", tab)
                time.sleep(0.3)   # v1.0과 동일: 0.3초
                filled = True
                logger.info(f"HTML보기 탭 클릭 성공: {xpath}")
                break
            except: continue

        if filled:
            # v1.0과 동일한 JS: offsetParent !== null 로 보이는 textarea 탐색
            r = self.driver.execute_script("""
                var tas = document.querySelectorAll('textarea');
                for(var i=0; i<tas.length; i++){
                    if(tas[i].offsetParent !== null){
                        tas[i].value = arguments[0];
                        tas[i].dispatchEvent(new Event('change',{bubbles:true}));
                        tas[i].dispatchEvent(new Event('input',{bubbles:true}));
                        return 'ok:'+i;
                    }
                }
                // 보이는 것 없으면 첫 번째 시도
                if(tas.length > 0){
                    tas[0].value = arguments[0];
                    tas[0].dispatchEvent(new Event('change',{bubbles:true}));
                    return 'hidden:0';
                }
                return 'not_found';
            """, editor_html)
            logger.info(f"textarea 입력 결과: {r}")

            # 편집보기 복귀 (v1.0과 동일)
            for xpath in ["//a[text()='편집보기']", "//span[text()='편집보기']"]:
                try:
                    tab = self.driver.find_element(By.XPATH, xpath)
                    self.driver.execute_script("arguments[0].click();", tab)
                    logger.info("편집보기 복귀")
                    break
                except: continue
            time.sleep(0.3)
        else:
            logger.warning("HTML보기 탭을 찾지 못함 - contenteditable 시도")
            # 폴백: contenteditable
            self.driver.execute_script("""
                var eds = document.querySelectorAll('[contenteditable="true"]');
                if(eds.length) { eds[0].innerHTML = arguments[0]; }
            """, editor_html)

    # ── 파일 첨부 ────────────────────────────────────
    def _attach_files(self, file_paths):
        valid = [fp for fp in (file_paths or []) if fp and os.path.exists(str(fp))]
        if not valid: return
        try:
            self.driver.execute_script("""
                document.querySelectorAll('input[type=file]').forEach(function(el){
                    el.style.cssText='display:block!important;opacity:1!important;';
                });
            """)
            time.sleep(0.3)
            inps = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            for fp in valid:
                if inps:
                    inps[0].send_keys(fp)
                    time.sleep(0.5)
                    logger.info(f"첨부: {os.path.basename(fp)}")
        except Exception as e:
            logger.warning(f"파일 첨부 실패: {e}")

    # ── 제목 조합 ─────────────────────────────────────
    @staticmethod
    def _make_title(data):
        parts = [(data.get(k) or "").strip()
                 for k in ["project_code","category","sub_category","item_type"]]
        prefix = "".join(f"[{p}]" for p in parts if p)
        main = (data.get("title_main") or "").strip()
        return f"{prefix} {main} 구매의 건".strip() if main else f"{prefix} 구매의 건".strip()

    # ── 기본 템플릿에서 변경 부분만 바꿔치기 ─────────
    def _build_complete_html(self, data):
        """
        기본 템플릿 HTML 로드 → 변경 필요한 셀만 교체 → 완성된 HTML 반환
        
        변경 위치 (template 분석 기준):
          table[2] row[1]  : 구매목적 내용
          table[2] row[5~8]: 품목 데이터 (9셀 × 4행, 초과 시 복제)
          table[2] row[9]  : 합계금액 td[1]
          table[4] row[1]  : 요청납기 날짜
          table[4] row[5~8]: 추천업체 데이터 (6셀 × 4행)
        나머지는 기본 템플릿 그대로 유지
        """
        def _as_list(v):
            if isinstance(v, list):
                return v
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return []
            return []

        items   = _as_list(data.get("items") or data.get("items_json") or [])
        vendors = _as_list(data.get("vendors") or data.get("vendors_json") or [])

        # 구매목적/상세내용 모두 누락 없이 반영
        # PURPOSE_INPUT_RESTORE_DEDUP_FIX_20260509
        # app.js에서는 reason/purpose/purpose_detail을 모두 보내고,
        # Bizbox 입력 직전에만 같은 문장 중복을 제거한다.
        purpose_candidates = [
            data.get("purpose"),
            data.get("purpose_detail"),
            data.get("reason"),
        ]
        purpose_lines = []
        seen_purpose_lines = set()
        for _p in purpose_candidates:
            for _line in str(_p or "").split("\n"):
                _line = _line.strip()
                if not _line:
                    continue
                _key = re.sub(r"\s+", " ", _line)
                if _key not in seen_purpose_lines:
                    seen_purpose_lines.add(_key)
                    purpose_lines.append(_line)
        purpose = "\n".join(purpose_lines).strip()
        req_d   = (data.get("required_date") or "")

        def fi(v):
            try: return f"{int(float(v or 0)):,}"
            except: return ""
        def fq(v):
            try:
                f = float(v or 0)
                return str(int(f)) if f == int(f) else str(f)
            except: return ""
        def fd(d):
            if not d: return "     202  년   월   일"
            p = str(d).split("-")
            return (f"     {p[0]} 년 {p[1]} 월 {p[2]} 일"
                    if len(p) == 3 else f"     {d}")

        def vendor_name(v):
            if isinstance(v, dict):
                return str(v.get("name") or v.get("vendor_name") or v.get("company") or "미정").strip() or "미정"
            return str(v or "미정").strip() or "미정"

        def item_amount(it):
            try:
                qty = float(it.get("quantity", 0) or 0)
                price = float(it.get("unit_price", 0) or 0)
                amount = float(it.get("amount", 0) or 0)
                return int(amount if amount else qty * price)
            except Exception:
                return 0

        def item_matches_vendor(it, v, idx):
            if not isinstance(it, dict):
                return False
            vi = it.get("vendor_index", None)
            if vi is not None and str(vi) != "":
                if isinstance(v, dict):
                    vix = v.get("vendor_index", idx)
                else:
                    vix = idx
                return str(vi) == str(vix)
            inv = str(it.get("vendor_name") or it.get("vendor") or "").strip()
            return bool(inv and inv == vendor_name(v))

        def vendor_amount(v, idx):
            matched = [it for it in items if item_matches_vendor(it, v, idx)]
            if not matched and len(vendors) <= 1:
                matched = items
            return sum(item_amount(it) for it in matched)

        if not os.path.exists(TEMPLATE_PATH):
            logger.warning("템플릿 없음, 폴백 사용")
            return self._fallback_html(data, items, vendors, purpose, req_d)

        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        tables = soup.find_all("table")
        pstyle = ("color:rgb(0,0,0);line-height:1.2;"
                  "font-family:'맑은 고딕';font-size:9pt;"
                  "margin-top:2.66px;margin-bottom:1.33px;")

        def new_p(text):
            p = soup.new_tag("p"); p["style"] = pstyle
            p.string = str(text); return p

        def setp(td, text):
            """td 내 <p> 모두 제거 후 새 <p> 추가"""
            for p in td.find_all("p"): p.decompose()
            td.append(new_p(text))

        # ── table[2]: 구매목적 + 품목 ──
        rows = tables[2].find_all("tr")

        # row[1]: 구매목적
        td_p = rows[1].find("td")
        if td_p:
            td_p.clear()
            for ln in ([l.strip() for l in purpose.split("\n") if l.strip()] or ["-"]):
                td_p.append(new_p(f" - {ln}"))

        # row[5~8]: 품목 4행
        # V18: 견적서가 여러 업체일 때 품목을 업체별로 묶고,
        #      각 업체 품목 바로 아래에 합계금액(업체명) 행을 삽입한다.
        item_rows = rows[5:9]
        total_row = rows[9]
        item_template = BeautifulSoup(str(item_rows[0]), "html.parser").find("tr") if item_rows else None
        subtotal_template = BeautifulSoup(str(total_row), "html.parser").find("tr")

        def make_item_row(no, it):
            row = BeautifulSoup(str(item_template), "html.parser").find("tr") if item_template else soup.new_tag("tr")
            if not row.find_all("td"):
                for _ in range(9):
                    row.append(soup.new_tag("td"))
            qty = float(it.get("quantity", 0) or 0)
            price = float(it.get("unit_price", 0) or 0)
            amt = item_amount(it)
            values = [str(no), it.get("item_name", ""), it.get("spec", ""),
                      fi(price), fq(qty), it.get("unit", "EA") or "EA",
                      fi(amt), it.get("axis", ""), it.get("maker", "")]
            for cell, value in zip(row.find_all("td"), values):
                setp(cell, value)
            return row, amt

        def make_subtotal_row(label, amount):
            row = BeautifulSoup(str(subtotal_template), "html.parser").find("tr")
            cells = row.find_all("td")
            if cells:
                setp(cells[0], label)
            if len(cells) >= 2:
                setp(cells[1], fi(amount))
            # 소계 행에는 부가세 선택 문구가 나오지 않게 뒤쪽 셀을 비운다.
            for c in cells[2:]:
                c.clear()
                c.append(new_p(""))
            return row

        def grouped_items():
            if not vendors:
                return [(None, list(enumerate(items)))]
            used = set()
            groups = []
            for vidx, vendor in enumerate(vendors):
                matched = [(i, it) for i, it in enumerate(items) if item_matches_vendor(it, vendor, vidx)]
                if not matched and len(vendors) == 1:
                    matched = list(enumerate(items))
                if matched:
                    for i, _ in matched:
                        used.add(i)
                    groups.append((vendor, matched))
            # 업체 매칭 정보가 없는 수기 입력 품목은 원래 순서대로 뒤에 표시한다.
            rest = [(i, it) for i, it in enumerate(items) if i not in used]
            if rest:
                groups.append((None, rest))
            return groups

        total = 0
        generated_rows = []
        item_no = 1
        for vendor, matched_items in grouped_items():
            group_total = 0
            for _, it in matched_items:
                new_row, amt = make_item_row(item_no, it)
                generated_rows.append(new_row)
                total += amt
                group_total += amt
                item_no += 1
            if vendor is not None:
                generated_rows.append(make_subtotal_row(f"합계금액({vendor_name(vendor)})", group_total))

        # 기존 템플릿의 빈 품목 4행은 제거하고, 생성한 품목/업체별 합계 행으로 교체한다.
        for r in item_rows:
            r.decompose()
        if not generated_rows:
            for _ in range(4):
                blank = BeautifulSoup(str(item_template), "html.parser").find("tr") if item_template else soup.new_tag("tr")
                for cell in blank.find_all("td"):
                    setp(cell, "")
                generated_rows.append(blank)
        for r in generated_rows:
            total_row.insert_before(r)

        # row[9]: 합계 td[1]
        tc = total_row.find_all("td")
        if len(tc) >= 2: setp(tc[1], fi(total))

        # ── table[4]: 요청납기 + 추천업체 ──
        r4 = tables[4].find_all("tr")

        # row[1]: 납기
        if len(r4) > 1:
            dcells = r4[1].find_all("td")
            if dcells: setp(dcells[-1], fd(req_d))

        # row[5~8]: 추천업체 4행
        for idx, row in enumerate(r4[5:9]):
            cells = row.find_all("td")
            if idx < len(vendors):
                v = vendors[idx]
                for cell, val in zip(cells[:6], [str(idx+1),
                        v.get("name",""), v.get("reason",""),
                        v.get("contact",""), v.get("email",""), v.get("fax","")]):
                    setp(cell, val)
            else:
                for cell in cells: setp(cell, "")

        return str(soup)

    def _fallback_html(self, data, items, vendors, purpose, req_d):
        def fi(v):
            try: return f"{int(float(v or 0)):,}"
            except Exception: return ""
        def vendor_name(v):
            if isinstance(v, dict):
                return str(v.get('name') or v.get('vendor_name') or v.get('company') or '미정').strip() or '미정'
            return str(v or '미정').strip() or '미정'
        def item_amount(it):
            try:
                q = float(it.get('quantity', 0) or 0)
                p = float(it.get('unit_price', 0) or 0)
                a = float(it.get('amount', 0) or 0)
                return int(a if a else q * p)
            except Exception:
                return 0
        def item_matches_vendor(it, v, idx):
            vi = it.get('vendor_index', None) if isinstance(it, dict) else None
            if vi is not None and str(vi) != '':
                vix = v.get('vendor_index', idx) if isinstance(v, dict) else idx
                return str(vi) == str(vix)
            inv = str(it.get('vendor_name') or it.get('vendor') or '').strip() if isinstance(it, dict) else ''
            return bool(inv and inv == vendor_name(v))
        def vendor_amount(v, idx):
            matched = [it for it in items if item_matches_vendor(it, v, idx)]
            if not matched and len(vendors) <= 1:
                matched = items
            return sum(item_amount(it) for it in matched)

        total = 0; rows = ""; vrows = ""
        def render_item_row(no, it):
            a = item_amount(it)
            try: p = float(it.get('unit_price', 0) or 0)
            except Exception: p = 0
            try: q = float(it.get('quantity', 0) or 0)
            except Exception: q = 0
            return (f"<tr><td>{no}</td><td>{it.get('item_name','')}</td>"
                    f"<td>{it.get('spec','')}</td><td>{fi(p)}</td><td>{int(q) if q == int(q) else q}</td>"
                    f"<td>{it.get('unit','EA') or 'EA'}</td><td>{fi(a)}</td>"
                    f"<td>{it.get('axis','')}</td><td>{it.get('maker','')}</td></tr>"), a
        if vendors:
            used = set(); no = 1
            for vi, v in enumerate(vendors):
                matched = [(i, it) for i, it in enumerate(items) if item_matches_vendor(it, v, vi)]
                if not matched and len(vendors) == 1:
                    matched = list(enumerate(items))
                gsum = 0
                for src_i, it in matched:
                    used.add(src_i)
                    html, a = render_item_row(no, it)
                    rows += html; total += a; gsum += a; no += 1
                if matched:
                    rows += f"<tr><td colspan='6'>합계금액({vendor_name(v)})</td><td>{fi(gsum)}</td><td></td><td></td></tr>"
            for src_i, it in enumerate(items):
                if src_i in used:
                    continue
                html, a = render_item_row(no, it)
                rows += html; total += a; no += 1
        else:
            for i, it in enumerate(items):
                html, a = render_item_row(i + 1, it)
                rows += html; total += a
        for i, v in enumerate(vendors):
            vrows += (f"<tr><td>{i+1}</td><td>{vendor_name(v)}</td>"
                      f"<td>{v.get('reason','') if isinstance(v, dict) else ''}</td><td>{v.get('contact','') if isinstance(v, dict) else ''}</td>"
                      f"<td>{v.get('email','') if isinstance(v, dict) else ''}</td><td>{v.get('fax','') if isinstance(v, dict) else ''}</td></tr>")
        plines = "".join(f"<p>- {l}</p>" for l in purpose.split("\n") if l.strip()) or "<p>-</p>"
        return (f"<center><table border='1' style='border-collapse:collapse;width:97%;'>"
                f"<tr><td colspan='9'><b>■ 구매목적</b></td></tr>"
                f"<tr><td colspan='9'>{plines}</td></tr>"
                f"<tr><td>No.</td><td>품명</td><td>규격</td><td>예상단가</td>"
                f"<td>수량</td><td>단위</td><td>예상금액</td><td>축구분</td><td>비고</td></tr>"
                f"{rows}"
                f"<tr><td colspan='6'>합 계 금 액</td><td>{fi(total)}</td><td></td><td>부가세별도</td></tr>"
                f"</table><table border='0' style='width:97%;'>"
                f"<tr><td colspan='7'><b>■ 요청납기</b> {req_d}</td></tr>"
                f"<tr><td>No.</td><td>추천업체</td><td>추천사유</td>"
                f"<td>담당자</td><td>이메일</td><td colspan='2'>FAX</td></tr>"
                f"{vrows}</table></center>")

    def close(self):
        if self.driver:
            try: self.driver.quit()
            except: pass
            self.driver = None


def auto_upload_purchase_request(request_data, user_id=None, user_pw=None):
    bot = BizboxAutomation(headless=False)
    if not bot.login(user_id, user_pw):
        msg = bot.last_error or "Bizbox 로그인 실패"
        if bot.last_debug_files:
            msg += "\n디버그 파일: " + json.dumps(bot.last_debug_files, ensure_ascii=False)
        return {"success": False, "message": msg, "debug_files": bot.last_debug_files, "alert": bot.last_alert}
    return bot.upload_purchase_request(request_data)
