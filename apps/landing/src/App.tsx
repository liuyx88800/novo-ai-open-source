import React, { useEffect, useRef, useState } from 'react';
import { Globe, ArrowRight, Quote, MonitorDown, X, Apple, BookOpen, Layers3, Sparkles, Wand2, ShieldCheck, ArrowUpRight, CheckCircle2 } from 'lucide-react';
import Button from './components/Button';
import WebGLBackground from './components/WebGLBackground';
import { useInViewAnimation } from './hooks/useInViewAnimation';

const App: React.FC = () => {
  // --- Section 1: Video Hero Logic ---
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoOpacity, setVideoOpacity] = useState(0);
  const [desktopModalOpen, setDesktopModalOpen] = useState(false);
  const fadingOutRef = useRef(false);
  const animationRef = useRef<number | null>(null);


  const animateOpacity = (target: number, duration: number) => {
    if (animationRef.current) cancelAnimationFrame(animationRef.current);
    const startOpacity = videoOpacity;
    const startTime = performance.now();
    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      setVideoOpacity(startOpacity + (target - startOpacity) * progress);
      if (progress < 1) animationRef.current = requestAnimationFrame(animate);
    };
    animationRef.current = requestAnimationFrame(animate);
  };

  const handleTimeUpdate = () => {
    const video = videoRef.current;
    if (!video || !video.duration) return;
    if (video.duration - video.currentTime <= 0.55 && !fadingOutRef.current) {
      fadingOutRef.current = true;
      animateOpacity(0, 500);
    }
  };

  const handleVideoEnded = () => {
    const video = videoRef.current;
    if (!video) return;
    setVideoOpacity(0);
    setTimeout(() => {
      video.currentTime = 0;
      video.play();
      fadingOutRef.current = false;
      animateOpacity(1, 500);
    }, 100);
  };

  // --- Section 3: Parallax Logic ---
  const parallaxRef = useRef<HTMLImageElement>(null);
  const [parallaxY, setParallaxY] = useState(0);

  useEffect(() => {
    const handleScroll = () => {
      if (!parallaxRef.current) return;
      const rect = parallaxRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const elementCenter = rect.top + rect.height / 2;
      const viewportCenter = viewportHeight / 2;
      const offset = (elementCenter - viewportCenter) * 0.12;
      setParallaxY(offset);
    };
    window.addEventListener('scroll', handleScroll);
    handleScroll();
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const [stickers, setStickers] = useState<{ id: number, x: number, y: number, rot: number, url: string }[]>([]);
  const lastSpawnRef = useRef(0);

  const marqueeImages = [
    "/lafai_ui_infinite_canvas.png",
    "/lafai_cinematic_landscape.png",
    "/lafai_3d_camera_control.png",
    "/lafai_studio_lighting.png",
    "/lafai_ui_infinite_canvas.png",
    "/lafai_cinematic_landscape.png"
  ];
  const capabilityCards = [
    { title: "无限画布", desc: "把提示词、参考图、生成结果和复用节点放在同一张创作地图里。", meta: "Canvas OS", icon: Layers3 },
    { title: "导演级控制", desc: "用运镜、光影和构图参数，把随机生成变成可控的镜头语言。", meta: "Director Mode", icon: Wand2 },
    { title: "多模型编排", desc: "在一个流程里调度图像、视频、反推和素材管理，减少反复切换。", meta: "Model Routing", icon: Sparkles },
    { title: "资产沉淀", desc: "保留每次创作的上下文、节点和成本数据，团队复盘更清晰。", meta: "Studio Memory", icon: ShieldCheck }
  ];
  const premiumCases = [
    { title: "品牌视觉短片", desc: "从主视觉到分镜预览，一张画布完成多轮风格推演。", url: "/lafai_cinematic_landscape.png" },
    { title: "影棚光影测试", desc: "快速比较不同灯位、材质和画面情绪，保留可追溯节点。", url: "/lafai_studio_lighting.png" },
    { title: "产品镜头探索", desc: "用 3D 运镜控制生成方向，让画面更接近商业成片。", url: "/lafai_3d_camera_control.png" }
  ];
  const workflowSteps = ["输入创意", "连接参考", "生成分支", "筛选成片"];

  const handlePartnerMouseMove = (e: React.MouseEvent) => {
    const now = Date.now();
    if (now - lastSpawnRef.current < 80) return;
    lastSpawnRef.current = now;
    const id = now;
    const newSticker = {
      id,
      x: e.clientX,
      y: e.clientY + window.scrollY,
      rot: Math.random() * 20 - 10,
      url: marqueeImages[Math.floor(Math.random() * marqueeImages.length)]
    };
    setStickers(prev => [...prev, newSticker]);
    setTimeout(() => setStickers(prev => prev.filter(s => s.id !== id)), 1000);
  };

  // --- Section Animations ---
  const heroAnim = useInViewAnimation();
  const quoteAnim = useInViewAnimation();
  const pricingAnim = useInViewAnimation();
  const partnerAnim = useInViewAnimation();

  // --- Auth Modal Logic ---
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [username, setUsername] = useState('');
  const [verifyCode, setVerifyCode] = useState('');
  const [captchaToken, setCaptchaToken] = useState('');
  const [captchaQuestion, setCaptchaQuestion] = useState('');
  const [captchaImage, setCaptchaImage] = useState('');
  const [captchaAnswer, setCaptchaAnswer] = useState('');
  const [captchaStartedAt, setCaptchaStartedAt] = useState(0);
  const [captchaLoading, setCaptchaLoading] = useState(false);
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [user, setUser] = useState<{username: string, email: string} | null>(() => {
    const saved = localStorage.getItem('lafai_user');
    return saved ? JSON.parse(saved) : null;
  });
  const appPath = () => (window as any).__NIUNIU_DESKTOP__ ? '/static/canvas.html' : '/workbench/';

  const goToApp = () => {
    console.log('goToApp called');
    if (user) {
      console.log('User authenticated, redirecting to app');
      window.location.href = appPath();
    } else {
      console.log('User not authenticated, opening login modal...');
      openAuth('login');
    }
  };

  const downloadMac = () => {
    window.location.href = '/downloads/LAFA-mac-latest.dmg';
  };

  const docsUrl = 'https://hcne037zdqdd.feishu.cn/wiki/TXIrwDa2FiWBS6kFTAqc5fgxnJe?from=from_copylink';

  useEffect(() => {
    // Only auto-redirect if we JUST logged in (to trigger the transition)
    const justLoggedIn = sessionStorage.getItem('just_logged_in');
    if (user && justLoggedIn) {
      sessionStorage.removeItem('just_logged_in');
      window.location.href = appPath();
    }
  }, [user]);

  const openAuth = (mode: 'login' | 'register') => {
    setAuthMode(mode);
    setShowAuthModal(true);
  };

  const loadCaptchaChallenge = async () => {
    setCaptchaLoading(true);
    try {
      const res = await fetch('/api/auth/challenge?purpose=register', { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok || !data.challenge) throw new Error(data.error || '人机验证加载失败');
      setCaptchaToken(data.challenge.id);
      setCaptchaQuestion(data.challenge.question);
      setCaptchaImage(data.challenge.image || '');
      setCaptchaStartedAt(data.challenge.issued_at || Date.now());
      setCaptchaAnswer('');
    } catch (err) {
      setCaptchaToken('');
      setCaptchaQuestion('');
      setCaptchaImage('');
      alert(err instanceof Error ? err.message : '人机验证加载失败，请刷新重试');
    } finally {
      setCaptchaLoading(false);
    }
  };

  useEffect(() => {
    if (showAuthModal && authMode === 'register') {
      loadCaptchaChallenge();
    }
  }, [showAuthModal, authMode]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('login') === '1' || params.get('login') === 'true') {
      openAuth('login');
    }
  }, []);

  const handleAuthSubmit = async () => {
    const endpoint = authMode === 'login' ? '/api/login' : '/api/register';
    try {
      const res = await fetch(`${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, username, code: verifyCode })
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem('lafai_user', JSON.stringify(data.user));
        setUser(data.user);
        setShowAuthModal(false);
        // 标记刚刚登录成功，用于显示动画
        sessionStorage.setItem('just_logged_in', 'true');
        window.location.href = appPath();
      } else {
        alert(data.error || '操作失败');
      }
    } catch (err) {
      alert('无法连接到服务器');
    }
  };

  const sendVerificationCode = async () => {
    if (!email) return alert('请输入邮箱');
    if (!captchaToken || !captchaAnswer.trim()) return alert('请先完成人机验证');
    setIsSendingCode(true);
    try {
      const res = await fetch('/api/send-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          captcha_token: captchaToken,
          captcha_answer: captchaAnswer,
          form_started_at: captchaStartedAt,
          website: ''
        })
      });
      if (res.ok) {
        alert('验证码已发送，请查收邮箱');
        loadCaptchaChallenge();
      } else {
        const data = await res.json();
        alert(data.error || '发送失败');
        loadCaptchaChallenge();
      }
    } catch (err) {
      alert('连接失败');
    } finally {
      setIsSendingCode(false);
    }
  };

  const logout = () => {
    localStorage.removeItem('lafai_user');
    setUser(null);
  };

  return (
    <div className="bg-white">
      {/* Auth Modal Overlay */}
      {showAuthModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-6">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowAuthModal(false)}></div>
          <div className="relative grid w-full max-w-4xl overflow-hidden rounded-[32px] bg-white shadow-2xl animate-fade-in-up md:grid-cols-[1fr_1.18fr]">
            {/* Left brand panel: logo */}
            <div className="relative hidden flex-col justify-between overflow-hidden bg-[#051A24] p-10 md:flex">
              <div className="pointer-events-none absolute inset-0 opacity-40" style={{ backgroundImage: 'radial-gradient(circle at 30% 22%, rgba(125,211,252,.18), transparent 34%), radial-gradient(circle at 78% 82%, rgba(245,158,11,.14), transparent 32%)' }} />
              <div className="relative flex flex-col items-start gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded-2xl bg-white shadow-[0_12px_30px_rgba(255,255,255,.2)]">
                    <img src="/logo.png" alt="Novo AI" className="h-10 w-10 object-contain" />
                  </div>
                  <span className="text-2xl font-black tracking-tight text-white mondwest">Novo AI</span>
                </div>
                <p className="mt-2 max-w-[220px] text-sm leading-relaxed text-white/55">
                  把提示词、参考图、生成结果和复用节点，放在同一张创作地图里。
                </p>
              </div>
              <div className="relative flex flex-col gap-2">
                <div className="flex items-center gap-2 text-[11px] font-medium tracking-wide text-white/40">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  无限画布 · 导演级控制 · 多模型编排
                </div>
              </div>
            </div>

            {/* Right form panel */}
            <div className="flex flex-col p-8 sm:p-10">
              <div className="mb-2 flex items-center gap-2 md:hidden">
                <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg bg-white shadow">
                  <img src="/logo.png" alt="Novo AI" className="h-6 w-6 object-contain" />
                </div>
                <span className="text-lg font-black text-[#051A24] mondwest">Novo AI</span>
              </div>
              <h3 className="text-3xl font-semibold mondwest mb-2">{authMode === 'login' ? '欢迎回来' : '开启创作之旅'}</h3>
              <p className="text-slate-500 text-sm mb-8">{authMode === 'login' ? '登录 Novo AI，继续你的创意工作流' : '注册 Novo AI，开启无限画布的视觉探索'}</p>

              <div className="space-y-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">邮箱地址</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@example.com"
                    className="w-full bg-slate-50 border-none rounded-2xl px-5 py-4 focus:ring-2 focus:ring-[#051A24] transition-all outline-none"
                  />
                </div>
                {authMode === 'register' && (
                  <>
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">用户名</label>
                      <input
                        type="text"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        placeholder="输入你的创作代号"
                        className="w-full bg-slate-50 border-none rounded-2xl px-5 py-4 focus:ring-2 focus:ring-[#051A24] transition-all outline-none"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">人机验证</label>
                      <div className="grid grid-cols-[156px_1fr] sm:grid-cols-[168px_1fr] gap-3">
                        <button
                          type="button"
                          onClick={loadCaptchaChallenge}
                          disabled={captchaLoading}
                          title="点击刷新验证码"
                          className="h-16 rounded-2xl bg-slate-100 overflow-hidden flex items-center justify-center cursor-pointer disabled:cursor-wait focus:ring-2 focus:ring-[#051A24] outline-none"
                        >
                          {captchaImage ? (
                            <img src={captchaImage} alt="图形验证码" className="h-full w-full object-cover select-none" draggable={false} />
                          ) : (
                            <span className="text-xs font-bold text-slate-400">{captchaLoading ? '加载中...' : (captchaQuestion || '请刷新')}</span>
                          )}
                        </button>
                        <input
                          type="text"
                          value={captchaAnswer}
                          onChange={(e) => setCaptchaAnswer(e.target.value.toUpperCase())}
                          placeholder="输入图形码"
                          maxLength={6}
                          className="min-w-0 bg-slate-50 border-none rounded-2xl px-5 py-4 focus:ring-2 focus:ring-[#051A24] transition-all outline-none uppercase tracking-widest"
                        />
                      </div>
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">验证码</label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={verifyCode}
                          onChange={(e) => setVerifyCode(e.target.value)}
                          placeholder="6位数字"
                          className="flex-1 bg-slate-50 border-none rounded-2xl px-5 py-4 focus:ring-2 focus:ring-[#051A24] transition-all outline-none"
                        />
                        <button
                          onClick={sendVerificationCode}
                          disabled={isSendingCode}
                          className="px-4 bg-slate-100 rounded-2xl text-xs font-bold text-[#051A24] hover:bg-slate-200 disabled:opacity-50 transition-colors"
                        >
                          {isSendingCode ? '发送中...' : '发送'}
                        </button>
                      </div>
                    </div>
                  </>
                )}
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">密码</label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full bg-slate-50 border-none rounded-2xl px-5 py-4 focus:ring-2 focus:ring-[#051A24] transition-all outline-none"
                  />
                </div>
                <Button onClick={handleAuthSubmit} className="w-full py-4 mt-4">{authMode === 'login' ? '立即登录' : '创建账号'}</Button>
              </div>

              {authMode === 'login' && (
                <button
                  type="button"
                  onClick={() => { window.location.href = '/workbench/?reset=1'; }}
                  className="mt-5 w-full text-center text-sm font-semibold text-[#051A24] underline underline-offset-4"
                >
                  找回密码
                </button>
              )}
              <div className="mt-5 text-center text-sm text-slate-500">
                {authMode === 'login' ? (
                  <span>还没有账号？ <button onClick={() => setAuthMode('register')} className="text-[#051A24] font-semibold underline">立即注册</button></span>
                ) : (
                  <span>已经有账号了？ <button onClick={() => setAuthMode('login')} className="text-[#051A24] font-semibold underline">直接登录</button></span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 1: DARK CINEMATIC HERO (FIRST SCREEN) */}
      <section className="relative h-screen bg-black overflow-hidden flex flex-col">
        <WebGLBackground />
        <video
          ref={videoRef}
          src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260328_115001_bcdaa3b4-03de-47e7-ad63-ae3e392c32d4.mp4"
          muted playsInline autoPlay
          onLoadedData={() => animateOpacity(1, 500)}
          onTimeUpdate={handleTimeUpdate}
          onEnded={handleVideoEnded}
          className="absolute inset-0 w-full h-full object-cover translate-y-[17%] pointer-events-none"
          style={{ opacity: videoOpacity }}
        />

        <nav className="relative z-20 px-6 py-6">
          <div className="rounded-full px-6 py-3 flex items-center justify-between max-w-5xl mx-auto backdrop-blur-md bg-white/5 border border-white/10">
            <div className="flex items-center gap-2">
              <Globe className="text-white" size={24} />
              <span className="text-white font-semibold text-lg mondwest">Novo AI</span>
            </div>
            <div className="hidden md:flex items-center gap-8">
              <a href="#feature" className="text-white/80 hover:text-white transition-colors text-sm font-medium">无限画布</a>
              <a href="#price" className="text-white/80 hover:text-white transition-colors text-sm font-medium">订阅方案</a>
              <a href="#about" className="text-white/80 hover:text-white transition-colors text-sm font-medium">关于我们</a>
              <a href={docsUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-white/80 hover:text-white transition-colors text-sm font-medium">
                <BookOpen size={15} />
                使用文档
              </a>
            </div>
            <div className="flex items-center gap-4">
              <button onClick={() => setDesktopModalOpen(true)} className="hidden sm:inline-flex items-center gap-2 rounded-full border border-white/15 bg-white text-[#051A24] px-4 py-2 text-sm font-semibold shadow-[0_12px_30px_rgba(255,255,255,.16)] hover:scale-[1.03] transition-transform">
                <MonitorDown size={16} />
                桌面版
              </button>
              {user ? (
                <div className="flex items-center gap-4">
                  <span className="text-white text-sm font-medium">{user.username}</span>
                  <button onClick={logout} className="text-white/60 text-xs hover:text-white transition-colors">退出</button>
                  <button onClick={goToApp} className="liquid-glass rounded-full px-6 py-2 text-white text-sm font-medium">进入画布</button>
                </div>
              ) : (
                <>
                  <button onClick={() => openAuth('register')} className="text-white text-sm font-medium hover:text-white/80 transition-colors">注册</button>
                  <button onClick={() => openAuth('login')} className="liquid-glass rounded-full px-6 py-2 text-white text-sm font-medium">登录</button>
                </>
              )}
            </div>
          </div>
        </nav>

        <div className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 text-center -translate-y-[15%]">
          <h1 className="text-7xl md:text-[10rem] font-[900] mb-8 tracking-[-0.05em] leading-none bg-gradient-to-b from-white to-white/10 bg-clip-text text-transparent animate-premium-blur-in" style={{ fontFamily: "'Inter', sans-serif" }}>
            Novo AI
          </h1>
          <div className="max-w-xl w-full space-y-6">
            <div className="liquid-glass rounded-full pl-6 pr-2 py-2 flex items-center gap-3">
              <input type="email" placeholder="输入邮箱开启创作预览" className="bg-transparent flex-1 border-none outline-none text-white placeholder:text-white/40 text-base" />
              <button onClick={goToApp} className="bg-white rounded-full p-3 text-black"><ArrowRight size={20} /></button>
            </div>
            <p className="text-white/60 text-sm">获取最新的 AI 视频创作洞察。订阅简报，不错过任何激动人心的更新。</p>
            <div className="pt-2">
              <button onClick={goToApp} className="liquid-glass rounded-full px-10 py-4 text-white text-sm font-medium hover:bg-white/10 transition-all">进入工作流演示</button>
            </div>
          </div>
        </div>
      </section>

      <main className="premium-main">
        {/* SECTION 2: PREMIUM SYSTEM */}
        <section className="relative overflow-hidden px-6 py-28 md:py-36">
          <div className="premium-orb premium-orb-a" />
          <div className="premium-orb premium-orb-b" />
          <div ref={heroAnim.ref} className={`${heroAnim.animationClass} relative z-10 mx-auto max-w-7xl`}>
            <div className="mb-14 grid gap-10 md:grid-cols-[1.05fr_.95fr] md:items-end">
              <div>
                <p className="premium-kicker" style={{ animationDelay: '0.1s' }}>Novo AI Studio</p>
                <h2 className="mt-5 max-w-4xl text-[42px] font-black leading-[.95] tracking-[-.04em] text-white md:text-[76px]" style={{ animationDelay: '0.2s' }}>
                  把 AI 生成，升级成可控的创作系统。
                </h2>
              </div>
              <div className="premium-copy" style={{ animationDelay: '0.3s' }}>
                <p>Novo AI 不是单次出图工具，而是一套面向短片、广告、IP 视觉和团队协作的无限画布工作台。</p>
                <p>从提示词、参考图、反推、分支结果到最终成片，所有创作线索都能在同一张画布里被看见、复用和沉淀。</p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-4">
              {capabilityCards.map((item, i) => {
                const Icon = item.icon;
                return (
                  <article key={item.title} className="premium-card group" style={{ animationDelay: `${0.12 * i + 0.2}s` }}>
                    <div className="mb-8 flex items-center justify-between">
                      <span className="premium-card-icon"><Icon size={20} /></span>
                      <span className="text-[10px] font-bold uppercase tracking-[.24em] text-white/35">{item.meta}</span>
                    </div>
                    <h3 className="text-2xl font-bold tracking-[-.03em] text-white">{item.title}</h3>
                    <p className="mt-4 text-sm leading-7 text-white/55">{item.desc}</p>
                  </article>
                );
              })}
            </div>
          </div>
        </section>

        {/* SECTION 3: INFINITE MARQUEE */}
        <section id="feature" className="relative overflow-hidden border-y border-white/10 py-10">
          <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-24 bg-gradient-to-r from-[#05070a] to-transparent md:w-44" />
          <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-24 bg-gradient-to-l from-[#05070a] to-transparent md:w-44" />
          <div className="flex animate-marquee whitespace-nowrap">
            {[...marqueeImages, ...marqueeImages].map((url, i) => (
              <div key={i} className="premium-shot mx-3 md:mx-5">
                <img src={url} className="h-[260px] w-auto rounded-[26px] object-cover md:h-[480px]" alt="Novo AI 视频与图像生成预览" />
              </div>
            ))}
          </div>
        </section>

        {/* SECTION 4: TESTIMONIAL QUOTE */}
        <section className="relative px-6 py-28 md:py-36">
          <div ref={quoteAnim.ref} className={`${quoteAnim.animationClass} mx-auto grid max-w-7xl gap-12 md:grid-cols-[.9fr_1.1fr] md:items-center`}>
            <div className="relative">
              <div className="premium-portrait-halo" />
              <img
                ref={parallaxRef}
                src="/user_portrait.png?v=3"
                className="relative z-10 aspect-[4/5] w-full max-w-md rounded-[34px] object-cover shadow-[0_45px_110px_rgba(0,0,0,.45)] transition-transform duration-100 ease-out"
                style={{ transform: `translateY(${parallaxY}px)` }}
                alt="Novo AI 创作者"
              />
            </div>
            <div>
              <Quote className="mb-8 h-10 w-10 text-white/70" style={{ animationDelay: '0.1s' }} />
              <p className="text-[34px] leading-[1.08] tracking-[-.045em] text-white md:text-[62px]" style={{ animationDelay: '0.2s' }}>
                “让灵感不再丢在聊天框里，而是在画布上形成一条能复盘、能扩展、能交付的创作链。”
              </p>
              <div className="mt-10 grid gap-3 sm:grid-cols-3" style={{ animationDelay: '0.3s' }}>
                {["节点式流程", "成本可追踪", "素材可复用"].map((item) => (
                  <div key={item} className="premium-stat">
                    <CheckCircle2 size={16} />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* SECTION 5: WORKFLOW */}
        <section id="price" className="px-6 py-28">
          <div ref={pricingAnim.ref} className={`${pricingAnim.animationClass} mx-auto max-w-7xl`}>
            <div className="premium-panel overflow-hidden">
              <div className="grid gap-10 p-8 md:grid-cols-[.85fr_1.15fr] md:p-12">
                <div>
                  <p className="premium-kicker">Workflow Engine</p>
                  <h3 className="mt-5 text-4xl font-black leading-tight tracking-[-.04em] text-white md:text-6xl">从一个想法，到一组可交付镜头。</h3>
                  <p className="mt-6 max-w-md text-base leading-8 text-white/55">不用反复开新窗口。你可以在同一张画布里接入参考、比较分支、保留最佳结果，并把它继续扩展成下一段画面。</p>
                  <button onClick={goToApp} className="mt-9 inline-flex items-center gap-3 rounded-full bg-white px-7 py-4 text-sm font-bold text-[#071018] transition-transform hover:scale-[1.03]">
                    进入画布
                    <ArrowUpRight size={16} />
                  </button>
                </div>
                <div className="premium-workflow">
                  {workflowSteps.map((step, i) => (
                    <div key={step} className="premium-workflow-step">
                      <span>{String(i + 1).padStart(2, '0')}</span>
                      <strong>{step}</strong>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* SECTION 6: PROJECTS */}
        <section className="px-6 py-28">
          <div className="mx-auto max-w-7xl">
            <div className="mb-12 flex flex-col justify-between gap-6 md:flex-row md:items-end">
              <div>
                <p className="premium-kicker">Selected Scenes</p>
                <h3 className="mt-4 text-4xl font-black tracking-[-.04em] text-white md:text-6xl">更接近成片的 AI 视觉工作流。</h3>
              </div>
              <p className="max-w-md text-sm leading-7 text-white/50">每一个项目都不只是图片展示，而是围绕参考、生成、筛选和复用搭建出的完整创作资产。</p>
            </div>
            <div className="grid gap-5 md:grid-cols-3">
              {premiumCases.map((p, i) => (
                <article key={p.title} className="premium-case group">
                  <img src={p.url} className="h-[360px] w-full object-cover transition-transform duration-700 group-hover:scale-105" alt={p.title} />
                  <div className="absolute inset-x-0 bottom-0 p-6">
                    <div className="rounded-[24px] border border-white/15 bg-black/45 p-5 text-white backdrop-blur-xl">
                      <span className="text-xs font-bold text-white/40">0{i + 1}</span>
                      <h4 className="mt-2 text-2xl font-bold tracking-[-.03em]">{p.title}</h4>
                      <p className="mt-3 text-sm leading-6 text-white/60">{p.desc}</p>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* SECTION 7: PARTNER MOUSE TRAIL */}
        <section className="relative overflow-hidden px-6 py-36 md:py-48" onMouseMove={handlePartnerMouseMove}>
          <div className="premium-cta-grid" />
          <div ref={partnerAnim.ref} className={`${partnerAnim.animationClass} relative z-20 mx-auto max-w-5xl text-center`}>
            <img src="/logo.png" className="mx-auto mb-8 h-20 w-20 rounded-[22px] object-cover shadow-[0_20px_70px_rgba(255,255,255,.18)]" alt="Novo AI logo" />
            <h2 className="text-[48px] font-black leading-[.98] tracking-[-.05em] text-white md:text-[96px]">让你的下一次生成，有作品级的秩序感。</h2>
            <p className="mx-auto mt-8 max-w-2xl text-base leading-8 text-white/55">从灵感到交付，Novo AI 帮你把每一次尝试都沉淀为可继续生长的视觉资产。</p>
            <Button onClick={goToApp} variant="tertiary" className="mx-auto mt-10 flex items-center gap-4 px-12 py-6 text-lg">
              立即开始创作
              <ArrowRight size={18} />
            </Button>
          </div>
          {stickers.map(s => (
            <img
              key={s.id}
              src={s.url}
              className="absolute z-10 h-auto w-32 rounded-xl border border-white/15 shadow-2xl pointer-events-none md:w-48 animate-fade-in-up"
              style={{
                left: s.x - 100,
                top: s.y - window.scrollY - 100,
                transform: `rotate(${s.rot}deg) scale(0.8)`,
                opacity: 0.8,
                transition: 'opacity 1s ease-out, transform 1s ease-out'
              }}
              onLoad={(e) => {
                (e.target as HTMLImageElement).style.opacity = '0';
                (e.target as HTMLImageElement).style.transform = `rotate(${s.rot}deg) scale(0.2)`;
              }}
              alt=""
            />
          ))}
        </section>

        {/* FOOTER */}
        <footer id="about" className="mx-auto max-w-7xl border-t border-white/10 px-6 py-20 text-white">
          <div className="flex flex-col justify-between gap-12 md:flex-row md:items-start">
            <div>
              <div className="flex items-center gap-3">
                <img src="/logo.png" className="h-11 w-11 rounded-xl object-cover" alt="Novo AI logo" />
                <span className="text-xl font-black tracking-[-.03em]">Novo AI</span>
              </div>
              <p className="mt-5 max-w-sm text-sm leading-7 text-white/45">AI 无限画布生成平台，为创作者和团队提供更完整的视觉生产工作流。</p>
            </div>
            <div className="grid grid-cols-2 gap-10 text-sm sm:grid-cols-3">
              <div className="flex flex-col gap-4">
                <h6 className="font-bold text-white">产品</h6>
                <a href="#feature" className="text-white/45 transition-colors hover:text-white">核心功能</a>
                <a href="#price" className="text-white/45 transition-colors hover:text-white">工作流</a>
                <a href={docsUrl} target="_blank" rel="noreferrer" className="text-white/45 transition-colors hover:text-white">使用文档</a>
                <a href="#about" className="text-white/45 transition-colors hover:text-white">关于我们</a>
              </div>
              <div className="flex flex-col gap-4">
                <h6 className="font-bold text-white">开始</h6>
                <button onClick={goToApp} className="text-left text-white/45 transition-colors hover:text-white">进入画布</button>
                <button onClick={() => setDesktopModalOpen(true)} className="text-left text-white/45 transition-colors hover:text-white">下载桌面版</button>
                <button onClick={() => openAuth('register')} className="text-left text-white/45 transition-colors hover:text-white">注册账号</button>
              </div>
              <div className="col-span-2 flex flex-col gap-4 sm:col-span-1">
                <h6 className="font-bold text-white">开发人员</h6>
                <a
                  href="https://github.com/csyqlz/VOZEB-PRO"
                  target="_blank"
                  rel="noreferrer"
                  className="group inline-flex min-h-11 items-center gap-3 rounded-xl border border-white/10 px-3 py-2 text-white/55 transition-colors hover:border-white/20 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
                  aria-label="访问 XOZEM 的 VOZEB PRO 项目"
                >
                  <img
                    src="https://github.com/csyqlz.png?size=96"
                    className="h-10 w-10 rounded-full border border-white/15 object-cover"
                    alt="XOZEM"
                    loading="lazy"
                  />
                  <span className="min-w-0">
                    <span className="block font-semibold text-white">XOZEM</span>
                    <span className="block truncate text-xs text-white/40 group-hover:text-white/60">VOZEB PRO · @csyqlz</span>
                  </span>
                </a>
              </div>
            </div>
          </div>
          <div className="mt-20 flex flex-col justify-between gap-4 border-t border-white/10 pt-8 text-xs font-semibold uppercase tracking-[.18em] text-white/35 md:flex-row">
            <span>Novo AI Studio © 2026</span>
            <span>Shenyang, China</span>
          </div>
        </footer>
      </main>

      <div className="fixed bottom-10 left-1/2 -translate-x-1/2 z-50">
        <div className="bg-white rounded-full px-8 py-3 flex items-center gap-8 custom-shadow-primary border border-slate-100">
          <span className="mondwest text-2xl font-bold text-[#051A24]">L</span>
          <button onClick={() => setDesktopModalOpen(true)} className="hidden sm:inline-flex items-center gap-2 text-[#051A24]/70 hover:text-[#051A24] text-sm font-semibold transition-colors">
            <MonitorDown size={16} />
            下载桌面版
          </button>
          <button onClick={goToApp} className="bg-[#051A24] text-white rounded-full px-6 py-2 text-sm font-medium hover:scale-105 transition-transform active:scale-95">
            立即生成
          </button>
        </div>
      </div>

      {desktopModalOpen && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center px-5 py-8 bg-black/55 backdrop-blur-xl" onClick={() => setDesktopModalOpen(false)}>
          <div className="relative w-full max-w-4xl overflow-hidden rounded-[36px] border border-white/70 bg-white text-[#071521] shadow-[0_35px_110px_rgba(0,0,0,.36)]" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setDesktopModalOpen(false)} className="absolute right-5 top-5 z-20 grid h-10 w-10 place-items-center rounded-full bg-white/80 text-slate-500 shadow-sm hover:text-slate-900">
              <X size={18} />
            </button>
            <div className="grid gap-0 md:grid-cols-[.92fr_1.08fr]">
              <div className="p-8 md:p-12">
                <div className="mb-8 inline-flex items-center gap-2 rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white">
                  <Apple size={16} />
                  macOS 桌面版
                </div>
                <h3 className="text-4xl md:text-6xl font-black tracking-[-.045em] leading-[.98]">
                  更快、<br />更安全、<br />更便捷。
                </h3>
                <p className="mt-6 max-w-md text-base md:text-lg leading-8 text-slate-500">
                  把无限画布装进电脑。素材与会话优先缓存在本机，拖拽更顺，打开更快，创作过程更沉浸。
                </p>
                <div className="mt-9 flex flex-col sm:flex-row gap-3">
                  <button onClick={downloadMac} className="rounded-full bg-[#0b1220] px-7 py-4 text-sm font-bold text-white shadow-[0_18px_42px_rgba(15,23,42,.24)] hover:scale-[1.02] transition-transform">
                    下载 macOS 版
                  </button>
                  <button onClick={goToApp} className="rounded-full border border-slate-200 bg-white px-7 py-4 text-sm font-bold text-slate-700 hover:bg-slate-50">
                    继续使用网页版
                  </button>
                </div>
                <p className="mt-5 text-xs font-semibold text-slate-400">
                  已提供 DMG 安装包。首次打开如提示不明开发者，可右键选择打开。
                </p>
              </div>
              <div className="desktop-liquid-stage relative min-h-[430px] overflow-hidden p-7 md:p-10">
                <div className="desktop-liquid-orb desktop-liquid-orb-a" />
                <div className="desktop-liquid-orb desktop-liquid-orb-b" />
                <div className="desktop-liquid-orb desktop-liquid-orb-c" />
                <div className="desktop-liquid-grid" />
                <div className="desktop-liquid-sweep" />
                <div className="desktop-liquid-shell relative h-full min-h-[360px] rounded-[34px] p-4">
                  <div className="desktop-liquid-window relative h-full overflow-hidden rounded-[28px] p-6 md:p-7">
                    <div className="relative z-10 flex items-center justify-between">
                      <div className="flex gap-2">
                        <span className="h-3 w-3 rounded-full bg-[#ff5f57]" />
                        <span className="h-3 w-3 rounded-full bg-[#febc2e]" />
                        <span className="h-3 w-3 rounded-full bg-[#28c840]" />
                      </div>
                      <span className="rounded-full border border-white/55 bg-white/40 px-3 py-1 text-[11px] font-bold text-slate-600 backdrop-blur-xl">NOVO DESKTOP</span>
                    </div>
                    <div className="relative z-10 mt-10 grid grid-cols-2 gap-4">
                      <div className="desktop-liquid-tile col-span-1 h-28 rounded-[28px]" />
                      <div className="desktop-liquid-tile desktop-liquid-tile-soft mt-8 h-24 rounded-[28px]" />
                      <div className="desktop-liquid-tile desktop-liquid-tile-wide col-span-2 mx-auto h-32 w-[72%] rounded-[30px]" />
                    </div>
                    <div className="desktop-floating-node desktop-floating-node-a" />
                    <div className="desktop-floating-node desktop-floating-node-b" />
                    <div className="desktop-floating-node desktop-floating-node-c" />
                    <div className="desktop-glass-thread desktop-glass-thread-a" />
                    <div className="desktop-glass-thread desktop-glass-thread-b" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
