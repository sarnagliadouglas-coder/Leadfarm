"""Paginas e servidor LOCAL (127.0.0.1) para os testes que usam navegador. Nada sai da maquina.
As fixtures que o usam (`base_url`, `pw`) vivem no conftest.py: UMA definicao so, porque dois
Playwrights sincronos vivos na mesma sessao colidem."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LONGO_CAPTCHA = ("<p>Formulario de contacto. Rellena tus datos.</p>" * 60
                  + "<p>Este sitio esta protegido por reCAPTCHA. No soy un robot. Verifica que eres humano.</p>")

PAGINAS = {
    "/ok": (200, """<!doctype html><html lang="es"><head><title>Clinica Ejemplo</title></head><body>
        <header><button class="navbar-toggler" onclick="document.getElementById('m').style.display='block'">Menu</button>
        <nav id="m" style="display:none"><a href="/a">Inicio</a><a href="/b">Servicios</a></nav></header>
        <h1>Clinica Ejemplo</h1>
        <form action="/enviar" method="post"><input name="n"><input type="submit" value="Enviar consulta"></form>
        <a href="tel:+34960000107">Llámanos</a> <a href="https://wa.me/34600123456">WhatsApp</a>
        <a href="mailto:hola@clinica.es">Escríbenos</a>
        <button>Pedir cita</button>
        <a class="btn btn-primary" href="/cita">Reservar ahora</a>
        <button style="display:none">Boton oculto</button>
        <button style="visibility:hidden">Boton invisible</button>
        <img src="/no-existe.png"><a href="/roto">Enlace roto</a>
        </body></html>"""),
    "/js": (200, """<!doctype html><html lang="es"><head><title>Montado por JS</title></head><body>
        <p>Cargando...</p><script>setTimeout(function(){
        var b=document.createElement('button'); b.textContent='Agendar por JS'; document.body.appendChild(b);}, 50);
        </script></body></html>"""),
    "/limites": (200, "<html><head><title>Muchos</title></head><body>"
                 + f"<button>{'x' * 300}</button>"                     # 1o: cai dentro do teto de quantidade
                 + "".join(f"<button>Botón {i}</button>" for i in range(60))
                 + "</body></html>"),
    "/404": (404, "<html><head><title>No encontrado</title></head><body><h1>404</h1>"
                  "<form action='/x'><input></form><button>Volver</button></body></html>"),
    "/500": (500, "<html><head><title>Error</title></head><body>Error interno del servidor</body></html>"),
    "/desafio403": (403, "<html><head><title>Just a moment...</title></head>"
                         "<body>Checking your browser before accessing the site.</body></html>"),
    "/desafio200": (200, "<html><head><title>Sitio</title></head><body>Verifica que eres humano</body></html>"),
    "/recaptcha": (200, f"<html><head><title>Contacto</title></head><body>{LONGO_CAPTCHA}"
                        "<form action='/e'><input></form></body></html>"),
    "/a": (200, "<html><title>a</title><body>a</body></html>"),
    "/b": (200, "<html><title>b</title><body>b</body></html>"),
    "/cita": (200, "<html><title>cita</title><body>cita</body></html>"),
    "/enviar": (200, "<html><title>e</title><body>e</body></html>"),
    "/menu-vermelho": (200, """<!doctype html><html><head><title>Menu</title>
    <style>body{margin:0;background:#fff}</style></head><body>
    <button class="navbar-toggler" onclick="document.getElementById('v').style.display='block'">Menu</button>
    <div id="v" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgb(255,0,0)"></div>
    <p>Contenido de la pagina</p></body></html>"""),

    # --- Passo C4b: os 4 padroes reais de falso positivo medidos em C5 -----------------------------

    # fisioficticia: telefone/WhatsApp/email como TEXTO no centro da pagina, sem link nenhum.
    "/fisioficticia-texto": (200, """<html><head><title>Fisioficticia-like</title></head><body>
        <h1>Bienvenido a Fisioficticia</h1>
        <p>Reserva tu cita en el telefono 860 000 109 o envia Whatsapp al 600 000 108
        contacto@fisioficticia-catorce.es</p></body></html>"""),

    # Ana Ficticia: menu "RESERVA CITA"/"CONTACTO" + botao "RESERVA", todos para a mesma pagina
    # interna, que tem o contato de verdade (link tel:).
    "/irene-like": (200, """<html><head><title>Irene-like</title></head><body>
        <nav><a href="/irene-contato">RESERVA CITA</a> <a href="/irene-contato">CONTACTO</a></nav>
        <a class="btn" href="/irene-contato">RESERVA</a></body></html>"""),
    "/irene-contato": (200, """<html><head><title>Contacto</title></head><body>
        <a href="tel:+34968111222">Llamar</a></body></html>"""),

    # Luis Ficticio: menu "Contacto" + botao flutuante "Contacto" + "Pedir cita previa", todos
    # para a mesma pagina interna, que tem WhatsApp.
    "/jesus-like": (200, """<html><head><title>Jesus-like</title></head><body>
        <nav><a href="/jesus-contato">Contacto</a></nav>
        <a class="btn-flotante" href="/jesus-contato">Contacto</a>
        <a href="/jesus-contato">Pedir cita previa</a></body></html>"""),
    "/jesus-contato": (200, """<html><head><title>Contacto</title></head><body>
        <a href="https://wa.me/34600222333">WhatsApp</a></body></html>"""),

    # FICTX: "Contacto" no menu e link do Facebook -- os DOIS apontam para dominio externo
    # desconhecido (nunca resolvido: o filtro de dominio barra ANTES de qualquer rede). Controle de
    # "sem contato visivel" genuino e de restricao de dominio ao mesmo tempo.
    "/fictx-like": (200, """<html><head><title>FICTX-like</title></head><body>
        <nav><a href="http://contato.exemplo-externo.invalido/fictx">Contacto</a></nav>
        <a href="http://facebook.exemplo-externo.invalido/fictxpage">Facebook</a></body></html>"""),

    # Botao de agendamento para sistema externo DESCONHECIDO: conta como sinal (decisao C4b item 3)
    # mas NUNCA e seguido (dominio nao esta na lista conhecida) -- nenhuma rede real e tentada.
    "/agendamento-externo-desconhecido": (200, """<html><head><title>Agenda</title></head><body>
        <a href="http://sistema-externo.invalido/reservar">Reservar cita</a></body></html>"""),

    # Controle: precos e CIF no texto, sem nenhum contato real -- nao pode disparar os regex.
    "/precos-cif": (200, """<html><head><title>Precios</title></head><body>
        <p>CIF: B12345678. Sesion individual 49,99€. Bono 5 sesiones 1.234,56 €.
        Copyright 2024. Codigo postal 30202.</p></body></html>"""),

    # 7 links internos (mais que o teto de 5): prova que o teto novo (5) e respeitado, nao o antigo (15).
    "/muitos-links": (200, "<html><head><title>Muchos links</title></head><body>"
                      + "".join(f'<a href="/l{i}">Link {i}</a>' for i in range(7))
                      + "</body></html>"),

    # Ja tem link_na_inicial (tel:) E tem um candidato de contato (que TAMBEM levaria a pagina com
    # contato, se seguido). So discrimina "nao seguiu porque ja tinha link_na_inicial" de "nao
    # seguiu por acaso" -- a subpagina TEM contato, entao so aparece se for seguida indevidamente.
    "/ja-tem-link": (200, """<html><head><title>Ja tem link</title></head><body>
        <a href="tel:+34965000111">Llamar</a>
        <a href="/ja-tem-link-contato">Contacto</a></body></html>"""),
    "/ja-tem-link-contato": (200, """<html><head><title>Contacto</title></head><body>
        <a href="tel:+34965000222">Llamar</a></body></html>"""),
}


class _Handler(BaseHTTPRequestHandler):
    def _responder(self, com_corpo):
        status, corpo = PAGINAS.get(self.path.split("?")[0], (404, "<html><body>nao existe</body></html>"))
        dados = corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        if com_corpo:
            self.wfile.write(dados)

    def do_GET(self):
        self._responder(True)

    def do_HEAD(self):
        self._responder(False)

    def log_message(self, *a):
        pass


def iniciar():
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor
