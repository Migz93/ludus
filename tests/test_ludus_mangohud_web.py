"""UI smoke checks using the host JavaScriptCore runtime when available."""
import ctypes
import ctypes.util
from pathlib import Path
import unittest


class MangoHudWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        library = ctypes.util.find_library('javascriptcoregtk-4.1')
        if not library: raise unittest.SkipTest('JavaScriptCore is unavailable')
        cls.js = ctypes.CDLL(library)
        ptr = ctypes.c_void_p
        cls.js.JSGlobalContextCreate.argtypes = [ptr]
        cls.js.JSGlobalContextCreate.restype = ptr
        cls.js.JSGlobalContextRelease.argtypes = [ptr]
        cls.js.JSStringCreateWithUTF8CString.argtypes = [ctypes.c_char_p]
        cls.js.JSStringCreateWithUTF8CString.restype = ptr
        cls.js.JSStringRelease.argtypes = [ptr]
        cls.js.JSCheckScriptSyntax.argtypes = [ptr, ptr, ptr, ctypes.c_int, ctypes.POINTER(ptr)]
        cls.js.JSCheckScriptSyntax.restype = ctypes.c_bool
        cls.js.JSEvaluateScript.argtypes = [ptr, ptr, ptr, ptr, ctypes.c_int, ctypes.POINTER(ptr)]
        cls.js.JSEvaluateScript.restype = ptr
        cls.js.JSValueToStringCopy.argtypes = [ptr, ptr, ctypes.POINTER(ptr)]
        cls.js.JSValueToStringCopy.restype = ptr
        cls.js.JSStringGetUTF8CString.argtypes = [ptr, ptr, ctypes.c_size_t]
        cls.js.JSStringGetUTF8CString.restype = ctypes.c_size_t
        cls.source = (Path(__file__).parents[1] / 'src/web/app.js').read_text()

    def execute(self, source, syntax=False):
        ctx = self.js.JSGlobalContextCreate(None)
        script = self.js.JSStringCreateWithUTF8CString(source.encode())
        error = ctypes.c_void_p()
        try:
            if syntax: self.js.JSCheckScriptSyntax(ctx, script, None, 1, ctypes.byref(error))
            else: self.js.JSEvaluateScript(ctx, script, None, None, 1, ctypes.byref(error))
            if error.value:
                message = self.js.JSValueToStringCopy(ctx, error, None)
                try:
                    buffer = ctypes.create_string_buffer(4096)
                    self.js.JSStringGetUTF8CString(message, buffer, len(buffer))
                    self.fail(buffer.value.decode())
                finally: self.js.JSStringRelease(message)
        finally:
            self.js.JSStringRelease(script)
            self.js.JSGlobalContextRelease(ctx)

    def test_full_application_syntax(self):
        self.execute(self.source, syntax=True)

    def test_controls_preview_validation_save_and_status(self):
        start = self.source.index('function mangoEnabled(')
        end = self.source.index('/* One at-a-glance', start)
        source = self.source[start:end]
        self.execute(r'''
        let request;
        const nodes = [];
        function el(tag, props, ...children) {
          const n = Object.assign({ tag, children: children.flat(Infinity).filter(Boolean), listeners: {},
            addEventListener(event, cb) { this.listeners[event] = cb; } }, props);
          if (tag === 'select') n.value = (n.children.find(x => x.selected) || n.children[0]).value;
          nodes.push(n);
          return n;
        }
        const card = (...children) => el('card', null, children);
        const cardHead = text => el('header', {text});
        const disclosure = (label, content) => el('details', {label}, content);
        const mutate = (button, options) => { request = options; };
        const settings = {global: {scopebuddy: true}, games: {}, mangohud: {
          global: { enabled: false, font_size: 32, position: 'top-right', fps: true,
            frametime: true, cpu_stats: true, cpu_temp: true, gpu_stats: true,
            gpu_temp: true, ram: true, vram: true, toggle_hud: 'Shift_R+F12' },
          positions: ['top-left','top-right'], games: {}, preview: 'initial'
        }};
        function assert(value, message) { if (!value) throw new Error(message); }
        function field(label) { return nodes.find(n => n['aria-label'] === label); }
        function button(text) { return nodes.find(n => n.tag === 'button' && n.text === text); }
        ''' + source + r'''
        mangoHudCard(settings);
        const save = button('Save MangoHud');
        assert(!save.disabled, 'valid defaults should be saveable');
        field('MangoHud font size').value = '100';
        field('MangoHud font size').listeners.input();
        assert(save.disabled, 'invalid font size must prevent save');
        field('MangoHud font size').value = '40';
        field('Enable MangoHud globally').checked = true;
        field('MangoHud font size').listeners.input();
        const preview = nodes.find(n => n.tag === 'code');
        assert(preview.textContent.includes('font_size=40\n'.replace('\\n','\n')), 'preview must update');
        save.listeners.click();
        assert(request.body.scope === 'mangohud-global', 'global API scope');
        assert(request.body.policy.enabled && request.body.policy.font_size === 40, 'global policy fields');
        button('Reset MangoHud and restore user settings').listeners.click();
        assert(request.body.scope === 'mangohud-reset', 'reset must target only MangoHud');
        nodes.length = 0;
        mangoHudCard(settings, '42');
        assert(!field('MangoHud font size'), 'game controls must not contain layouts');
        field('Game MangoHud policy').value = 'enabled';
        button('Save MangoHud').listeners.click();
        assert(request.body.scope === 'mangohud-game' && request.body.policy.mode === 'enabled', 'game API scope');
        assert(mangoApplicationState({status:'applied',mangohud_status:'mangoapp'}, true, {})[1] === 'Applied — MangoApp via ScopeBuddy', 'MangoApp status');
        assert(mangoApplicationState({status:'pending-apply',mangohud_status:'mangoapp'}, true, {})[1] === 'Pending apply', 'do not show stale applied state');
        assert(mangoApplicationState({status:'conflict',error:'manual change'}, true, {})[1].startsWith('Blocked'), 'conflict status');
        assert(mangoApplicationState({status:'disabled'}, false, {mangohud:{error:'old config error'}})[1] === 'Disabled', 'disabled games must not inherit player HUD errors');
        assert(mangoApplicationState({status:'disabled'}, true, {mangohud:{error:'current config error'}})[1] === 'Error', 'enabled games must report config errors');
        ''')

    def test_player_history_and_replacement_explanation(self):
        source = self.source[self.source.index('function playerApplicationCard('):self.source.index('async function viewGames(')]
        self.execute(r'''
        const nodes = [];
        let request;
        function el(tag, props, ...children) {
          const n = Object.assign({tag,children:children.flat(Infinity),listeners:{},
            addEventListener(event, cb) { this.listeners[event] = cb; }},props);
          nodes.push(n); return n;
        }
        const card = (...children) => el('card',null,...children);
        const cardHead = text => el('header',{text});
        const displayName = user => user;
        const applicationStatus = () => null;
        const dpiApplicationState = () => [];
        const launchApplicationState = () => [];
        const mangoApplicationState = () => [];
        const mangoEnabled = () => true;
        const disclosure = (label,body) => el('details',{label},body);
        const mutate = (node,value) => { request=value; };
        ''' + source + r'''
        playerApplicationCard({games:{},global:{}}, {games:{},global:{},users:{alice:{accounts:{'123':{'42':{
          status:'conflict', hud_manual_backups:['first private command','second private command']
        }}}}}}, '42');
        for (const command of ['first private command','second private command']) {
          if (!nodes.some(n => n.tag === 'code' && n.text === command)) throw new Error('command history missing');
        }
        nodes.find(n => n.text === 'Replace temporarily').listeners.click();
        if (!request.success.includes('baseline') || !request.success.includes('history')) throw new Error('replacement explanation missing');
        ''')
