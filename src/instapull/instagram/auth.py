"""Login y sesion de Instagram.

Instaloader hace el login interactivo (con 2FA y checkpoints) y persiste la
sesion en disco. Esa misma sesion se puentea a instagrapi via `sessionid`,
porque instaloader no expone colecciones por nombre, comentarios ni DMs.
"""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Any

from ..config import Config
from ..logging_setup import get_logger
from .ratelimit import ActionBlocked, SessionExpired, clasificar_error

log = get_logger(__name__)


def _url_de_checkpoint(texto: str) -> str:
    """Saca la URL del checkpoint del mensaje de instaloader, ya absoluta."""
    for palabra in texto.replace("\n", " ").split(" "):
        if palabra.startswith("/") and "?" in palabra:
            return "https://www.instagram.com" + palabra
        if palabra.startswith("https://"):
            return palabra.rstrip(" -")
    return "https://www.instagram.com/"


def _mensaje_checkpoint(detalle: str) -> str:
    """Instrucciones concretas para desbloquear la cuenta y reintentar."""
    return (
        "Instagram pide aprobar este inicio de sesion (checkpoint).\n"
        f"1) Abri esta direccion en el navegador, logueado con esa cuenta:\n   "
        f"{_url_de_checkpoint(detalle)}\n"
        "2) Segui los pasos y aproba el acceso (o hacelo desde la app de Instagram: "
        "te llega una notificacion de 'Intento de inicio de sesion').\n"
        "3) Volve a correr `instapull login`."
    )


def _pedir_codigo(motivo: str) -> str:
    print(f"\n>>> Instagram pide un codigo de verificacion ({motivo}).")
    print(">>> Revisa tu app de autenticacion, SMS o email.")
    return input(">>> Codigo: ").strip()


class InstagramSession:
    """Sesion viva: instaloader para el login, instagrapi para las acciones."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.username: str = config.secrets.ig_username
        self._password: str = config.secrets.ig_password
        self._sessionid_manual: str = config.secrets.ig_sessionid
        self.loader: Any = None
        self.client: Any = None

    # --- credenciales -------------------------------------------------

    def _credenciales(self, pedir: bool = True) -> tuple[str, str]:
        usuario = self.username
        clave = self._password
        if not usuario and pedir:
            usuario = input("Usuario de Instagram: ").strip()
        if not clave and pedir:
            clave = getpass.getpass("Contrasena de Instagram (no se guarda): ")
        if not usuario or not clave:
            raise SessionExpired(
                "Faltan credenciales. Defini IG_USERNAME e IG_PASSWORD, o corre "
                "`instapull login` para ingresarlas por consola."
            )
        self.username = usuario
        self._password = clave
        return usuario, clave

    # --- instaloader --------------------------------------------------

    def _nuevo_loader(self) -> Any:
        import instaloader

        return instaloader.Instaloader(
            quiet=True,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            max_connection_attempts=2,
        )

    def _sesion_desde_cookie(self) -> Any:
        """Arma la sesion a partir de un `sessionid` copiado del navegador.

        Instagram bloquea el login por contrasena de instaloader en cuentas que
        marca como sospechosas (checkpoint infinito). Reusar la cookie de una
        sesion que el usuario ya aprobo en su navegador esquiva ese muro.
        """
        loader = self._nuevo_loader()
        loader.context._session.cookies.set(  # noqa: SLF001
            "sessionid", self._sessionid_manual, domain=".instagram.com"
        )
        # test_login usa un query_hash de graphql que Instagram ya no responde
        # (devuelve HTML). Si falla, la cookie la valida instagrapi en connect().
        try:
            usuario = loader.test_login()
        except Exception as exc:  # noqa: BLE001
            log.warning("test_login_instaloader_fallo", error=str(exc)[:120])
            usuario = None
        if not usuario:
            return loader
        loader.context.username = usuario
        self.username = usuario
        session_file: Path = self.config.session_path
        session_file.parent.mkdir(parents=True, exist_ok=True)
        loader.save_session_to_file(str(session_file))
        log.info("sesion_desde_cookie", usuario=usuario, sesion=str(session_file))
        return loader

    def _login_instaloader(self, interactivo: bool) -> Any:
        """Devuelve un Instaloader logueado, reusando la sesion si existe."""
        import instaloader

        loader = self._nuevo_loader()
        session_file: Path = self.config.session_path

        # 0) Cookie del navegador: gana sobre todo lo demas
        if self._sessionid_manual:
            return self._sesion_desde_cookie()

        # 1) Intentar reusar la sesion guardada
        if session_file.exists() and self.username:
            try:
                loader.load_session_from_file(self.username, str(session_file))
                if loader.test_login():
                    log.info("sesion_reutilizada", usuario=self.username)
                    return loader
                log.warning("sesion_expirada", archivo=str(session_file))
            except Exception as exc:  # noqa: BLE001
                log.warning("sesion_ilegible", error=str(exc)[:200])
        elif session_file.exists() and not self.username:
            log.warning(
                "sesion_sin_usuario",
                detalle="Hay sesion guardada pero falta IG_USERNAME para cargarla",
            )

        if not interactivo:
            raise SessionExpired(
                "No hay una sesion valida. Corre `instapull login` para autenticarte."
            )

        # 2) Login nuevo
        usuario, clave = self._credenciales(pedir=True)
        loader = self._nuevo_loader()
        try:
            loader.login(usuario, clave)
        except instaloader.exceptions.TwoFactorAuthRequiredException:
            codigo = _pedir_codigo("verificacion en dos pasos")
            loader.two_factor_login(codigo)
        except instaloader.exceptions.BadCredentialsException as exc:
            raise SessionExpired(f"Usuario o contrasena incorrectos: {exc}") from exc
        except instaloader.exceptions.ConnectionException as exc:
            propio = clasificar_error(exc)
            if isinstance(propio, ActionBlocked):
                raise ActionBlocked(_mensaje_checkpoint(str(exc))) from exc
            raise
        # Debe ir DESPUES de las anteriores: LoginException es la clase padre de
        # BadCredentialsException y TwoFactorAuthRequiredException.
        except instaloader.exceptions.LoginException as exc:
            texto = str(exc)
            if "checkpoint" in texto.lower() or "challenge" in texto.lower():
                raise ActionBlocked(_mensaje_checkpoint(texto)) from exc
            raise SessionExpired(f"Instagram rechazo el login: {texto}") from exc

        session_file.parent.mkdir(parents=True, exist_ok=True)
        loader.save_session_to_file(str(session_file))
        log.info("login_ok", usuario=usuario, sesion=str(session_file))
        return loader

    # --- instagrapi ---------------------------------------------------

    def _sessionid(self, loader: Any) -> str:
        """Extrae la cookie `sessionid` del contexto de instaloader."""
        try:
            cookies = loader.context._session.cookies  # noqa: SLF001
            valor = cookies.get("sessionid", domain=".instagram.com") or cookies.get(
                "sessionid"
            )
        except Exception as exc:  # noqa: BLE001
            raise SessionExpired(f"No se pudo leer la cookie de sesion: {exc}") from exc
        if not valor:
            raise SessionExpired("La sesion no contiene `sessionid`. Volve a loguearte.")
        return str(valor)

    def _login_instagrapi(self, sessionid: str) -> Any:
        from instagrapi import Client

        cl = Client()
        cl.delay_range = list(self.config.instagram.request_delay_seconds)
        cl.challenge_code_handler = lambda _username, choice: _pedir_codigo(str(choice))
        try:
            cl.login_by_sessionid(sessionid)
        except Exception as exc:  # noqa: BLE001
            propio = clasificar_error(exc)
            raise (propio or SessionExpired(str(exc))) from exc
        return cl

    # --- API publica --------------------------------------------------

    def connect(self, interactivo: bool = False) -> "InstagramSession":
        """Deja `self.loader` y `self.client` listos para usar."""
        self.loader = self._login_instaloader(interactivo=interactivo)
        self.client = self._login_instagrapi(self._sessionid(self.loader))
        me = getattr(self.client, "username", "") or self.username
        log.info("conectado", usuario=me)
        self.username = me
        return self

    def login_interactivo(self) -> "InstagramSession":
        """Fuerza el flujo de login y guarda la sesion."""
        return self.connect(interactivo=True)
