/**
 * 路由表（五个页面）。
 *
 *   /login            登录页      —— 整页跳转认证中心，回调后回到 /
 *   /                 分析工作台  —— 会话列表 + 消息流 + 实时进度 + 附件 + 结果
 *   /history          历史会话    —— 全部会话的检索、改名、批量删除
 *   /result/:taskId   分析结果详情 —— 六大模块标准化输出 + 导出
 *   /admin            管理控制台  —— 配置热重载、功能开关、数据源、场景/工具、日志
 */

import { createRouter, createWebHistory } from 'vue-router'

import { useUserStore } from '@/store/user'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, blank: true, title: '登录' },
  },
  {
    path: '/',
    name: 'workspace',
    component: () => import('@/views/WorkspaceView.vue'),
    meta: { title: '分析工作台', needConversation: true },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
    meta: { title: '历史会话' },
  },
  {
    path: '/result/:taskId',
    name: 'result',
    component: () => import('@/views/ResultView.vue'),
    meta: { title: '分析结果详情' },
    props: true,
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/AdminView.vue'),
    meta: { title: '管理控制台', requiresAdmin: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const user = useUserStore()

  // 首次进入时确认登录态（依赖后端 HttpOnly Cookie，前端无法自行判断）
  if (!user.loaded) {
    await user.fetchMe({ silent: true })
  }
  user.fetchPublicConfig()

  if (to.meta.public) {
    // 已登录用户访问登录页直接回工作台
    return user.isLoggedIn && to.name === 'login' ? { name: 'workspace' } : true
  }

  if (!user.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && !user.isAdmin) {
    return { name: 'workspace', query: { denied: 'admin' } }
  }

  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · 经营多轮归因分析系统`
    : '经营多轮归因分析系统'
})

export default router
