import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  BarChart3,
  Mic,
  Shield,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from 'lucide-react'
import ParticleBackground from '../components/ParticleBackground'
import {
  pageVariants,
  navbarVariants,
  badgeVariants,
  heroTextVariants,
  subtitleVariants,
  buttonsContainerVariants,
  buttonVariants,
  cardsContainerVariants,
  cardVariants,
  ctaVariants,
  footerVariants,
  iconPulseVariants,
} from '../animations/homeVariants'

const navItems = [
  { label: 'Features', href: '#features' },
  { label: 'Security', href: '#security' },
  { label: 'Performance', href: '#performance' },
]

const featureCards = [
  {
    title: 'Voice-to-Insight Intelligence',
    description:
      'Turn natural language questions into chart-ready insights in seconds with contextual AI interpretation.',
    icon: Mic,
  },
  {
    title: 'Real-Time Decision Layer',
    description:
      'Monitor critical KPIs with live data pipelines and instant visual response built for fast business action.',
    icon: TrendingUp,
  },
  {
    title: 'Precision Team Workflows',
    description:
      'Role-based access, collaboration controls, and shared workspace governance designed for modern analytics teams.',
    icon: Users,
  },
  {
    title: 'Strategic Planning Engine',
    description:
      'Model business trends, spot anomalies, and align decisions across stakeholders from one intelligence layer.',
    icon: Target,
  },
]

function Home() {
  return (
    <motion.div
      variants={pageVariants}
      initial="hidden"
      animate="visible"
      className="relative min-h-screen overflow-hidden"
    >
      <ParticleBackground />

      <div className="relative z-10">
        <motion.nav
          variants={navbarVariants}
          className="sticky top-0 z-20 border-b border-brand-700/30 bg-brand-950/80 backdrop-blur-xl"
        >
          <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-4 lg:px-10">
            <div className="flex items-center space-x-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-700/80 shadow-[0_0_20px_rgba(69,53,212,0.35)]">
                <BarChart3 className="h-5 w-5 text-brand-100" />
              </div>
              <span className="bg-gradient-to-r from-brand-300 to-fire-400 bg-clip-text font-['Syne'] text-2xl font-extrabold text-transparent">
                BI Voice Agent
              </span>
            </div>

            <div className="hidden items-center gap-8 md:flex">
              {navItems.map((item) => (
                <a
                  key={item.label}
                  href={item.href}
                  className="group relative text-sm font-medium text-brand-200 transition-colors hover:text-white"
                >
                  {item.label}
                  <span className="absolute -bottom-1 left-0 h-[2px] w-0 bg-gradient-to-r from-brand-300 to-fire-400 transition-all duration-300 group-hover:w-full" />
                </a>
              ))}
            </div>

            <Link
              to="/signup"
              className="inline-flex items-center rounded-xl border border-fire-500/70 px-4 py-2 text-sm font-semibold text-fire-400 transition-all duration-300 hover:bg-gradient-to-r hover:from-brand-500 hover:to-fire-500 hover:text-white"
            >
              Launch Now
            </Link>
          </div>
        </motion.nav>

        <section className="mx-auto flex w-full max-w-6xl flex-col items-center px-6 pb-16 pt-24 text-center lg:pt-28">
          <motion.div variants={badgeVariants} className="relative mb-8 inline-flex">
            <span className="absolute inset-0 rounded-full border border-brand-400/60" />
            <motion.span
              className="absolute inset-0 rounded-full border border-fire-400/60"
              animate={{ scale: [1, 1.08, 1], opacity: [0.3, 0.75, 0.3] }}
              transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }}
            />
            <span className="relative inline-flex items-center gap-2 rounded-full border border-brand-400/40 bg-surface-glass px-5 py-2 text-sm font-medium text-brand-100 backdrop-blur-md">
              <Sparkles className="h-4 w-4 text-fire-400" />
              <span>{'\u2726'} Next-Gen Analytics Platform</span>
            </span>
          </motion.div>

          <motion.h1 variants={heroTextVariants} className="mb-6 text-5xl font-extrabold leading-[1.05] text-white md:text-7xl">
            <span className="block">Transform Your</span>
            <span className="animate-gradient block bg-gradient-to-r from-brand-300 via-fire-400 to-amber-400 bg-clip-text text-transparent">
              Data Into Power
            </span>
          </motion.h1>

          <motion.p
            variants={subtitleVariants}
            className="mb-12 max-w-xl text-lg font-light leading-relaxed text-brand-200 md:text-xl"
          >
            Build high-impact dashboards from voice commands and natural prompts, then deliver
            real-time clarity to every decision maker.
          </motion.p>

          <motion.div variants={buttonsContainerVariants} className="flex flex-col items-center gap-4 sm:flex-row">
            <motion.div variants={buttonVariants} whileHover="hover" whileTap="tap">
              <Link
                to="/signup"
                className="inline-flex items-center gap-3 rounded-xl bg-gradient-to-r from-brand-500 to-fire-500 px-8 py-4 text-base font-semibold text-white shadow-[0_0_30px_rgba(255,45,120,0.35)] transition-all duration-300 hover:shadow-[0_0_40px_rgba(255,45,120,0.5)]"
              >
                <span>Create Free Account</span>
                <ArrowRight className="h-5 w-5" />
              </Link>
            </motion.div>
            <motion.div variants={buttonVariants} whileHover="hover" whileTap="tap">
              <Link
                to="/login"
                className="inline-flex items-center rounded-xl border border-brand-400/50 bg-surface-glass px-8 py-4 text-base font-semibold text-brand-100 transition-all duration-300 hover:border-brand-300 hover:bg-[var(--c-card-bg)]/10"
              >
                Sign In
              </Link>
            </motion.div>
          </motion.div>
        </section>

        <section id="features" className="mx-auto w-full max-w-7xl px-6 py-16 lg:px-10">
          <motion.div variants={cardsContainerVariants} className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
            {featureCards.map((card, index) => {
              const Icon = card.icon
              return (
                <motion.article
                  key={card.title}
                  custom={index}
                  variants={cardVariants}
                  whileHover="hover"
                  className="rounded-2xl border border-brand-400/25 bg-[var(--c-card-bg)] p-6 backdrop-blur-md"
                >
                  <div className="mb-5 inline-flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-brand-700 to-brand-600">
                    <Icon className="h-6 w-6 text-white" />
                  </div>
                  <h3 className="mb-3 text-2xl font-bold text-brand-100">{card.title}</h3>
                  <p className="text-sm leading-relaxed text-brand-200">{card.description}</p>
                </motion.article>
              )
            })}
          </motion.div>
        </section>

        <section
          id="security"
          className="mt-12 border-t border-brand-700/30 py-20"
          style={{
            background:
              'radial-gradient(circle at center, rgba(45,31,163,0.45) 0%, rgba(8,5,32,0.25) 45%, rgba(3,1,10,0) 80%)',
          }}
        >
          <motion.div
            variants={ctaVariants}
            className="mx-auto flex w-full max-w-4xl flex-col items-center px-6 text-center"
          >
            <motion.div variants={iconPulseVariants} animate="animate" className="mb-8 rounded-full bg-brand-700/70 p-5 shadow-[0_0_35px_rgba(108,92,231,0.5)]">
              <Shield className="h-10 w-10 text-amber-400" />
            </motion.div>
            <h2 className="mb-4 text-4xl font-extrabold text-white md:text-5xl">
              Secure Intelligence, Built for Speed
            </h2>
            <p id="performance" className="mb-10 max-w-2xl text-lg text-brand-200">
              Bring teams, data, and AI guidance into one premium workspace designed for high-trust
              analytics execution.
            </p>
            <Link
              to="/signup"
              className="inline-flex items-center gap-3 rounded-xl bg-gradient-to-r from-brand-500 to-fire-500 px-10 py-4 text-lg font-semibold text-white shadow-[0_0_35px_rgba(255,45,120,0.38)] transition-all duration-300 hover:scale-[1.03] hover:shadow-[0_0_50px_rgba(255,45,120,0.55)]"
            >
              Start Free Today
              <ArrowRight className="h-5 w-5" />
            </Link>
          </motion.div>
        </section>

        <motion.footer variants={footerVariants} className="border-t border-brand-700/20 py-8">
          <div className="mx-auto flex w-full max-w-7xl items-center justify-center px-6 text-sm text-brand-300">
            BI Voice Agent {'\u2022'} Voice-Powered Analytics Platform
          </div>
        </motion.footer>
      </div>
    </motion.div>
  )
}

export default Home
