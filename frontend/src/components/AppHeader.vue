<script setup>
/** 顶栏：品牌、主导航、后端健康状态、当前用户与登出。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'

import { useUserStore } from '@/store/user'
import { useChatStore } from '@/store/chat'
import { useConversationStore } from '@/store/conversation'
import { fetchHealth } from '@/api/auth'
import { roleLabel } from '@/utils/constants'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const chat = useChatStore()
const conversations = useConversationStore()

const health = ref(null)

const activeNav = computed(() => {
  if (route.name === 'result') return 'workspace'
  return route.name
})

const systemName = computed(() => user.publicConfig?.system_name || '经营多轮归因分析系统')

const healthMeta = computed(() => {
  if (!health.value) return { type: 'info', text: '状态未知' }
  if (health.value.status === 'ok') return { type: 'success', text: '服务正常' }
  return { type: 'warning', text: '服务降级' }
})

onMounted(async () => {
  try {
    health.value = await fetchHealth()
  } catch {
    health.value = { status: 'down', database: 'error' }
  }
})

function go(name) {
  router.push({ name })
}

async function handleLogout() {
  try {
    await ElMessageBox.confirm('退出后需要重新通过认证中心登录，确认退出？', '退出登录', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  chat.clear()
  conversations.items = []
  await user.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <header class="app-header">
    <div class="brand" @click="go('workspace')">
      <div class="brand-logo">归因</div>
      <div class="brand-text">
        <div class="brand-title">{{ systemName }}</div>
        <div class="brand-sub">多轮对话 · 证据可追溯</div>
      </div>
    </div>

    <nav class="nav">
      <button
        class="nav-item"
        :class="{ active: activeNav === 'workspace' }"
        @click="go('workspace')"
      >
        <el-icon><ChatDotSquare /></el-icon>
        <span>分析工作台</span>
      </button>
      <button
        class="nav-item"
        :class="{ active: activeNav === 'history' }"
        @click="go('history')"
      >
        <el-icon><Files /></el-icon>
        <span>历史会话</span>
      </button>
      <button
        v-if="user.isAdmin"
        class="nav-item"
        :class="{ active: activeNav === 'admin' }"
        @click="go('admin')"
      >
        <el-icon><Setting /></el-icon>
        <span>管理控制台</span>
      </button>
    </nav>

    <div class="right">
      <el-tag :type="healthMeta.type" effect="plain" size="small" round>
        <span class="dot" :class="`dot--${healthMeta.type}`" />
        {{ healthMeta.text }}
      </el-tag>

      <el-dropdown trigger="click" @command="handleLogout">
        <div class="user">
          <div class="avatar">{{ user.me?.avatar_text || '—' }}</div>
          <div class="user-text">
            <div class="user-name">{{ user.displayName }}</div>
            <div class="user-role">{{ roleLabel(user.me?.role) }}</div>
          </div>
          <el-icon class="caret"><ArrowDown /></el-icon>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>
              账号：{{ user.me?.username || '—' }}
            </el-dropdown-item>
            <el-dropdown-item disabled>
              令牌剩余：{{ user.me?.token_expires_in ?? 0 }} 秒
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  height: var(--jy-header-height);
  flex: 0 0 var(--jy-header-height);
  display: flex;
  align-items: center;
  gap: 28px;
  padding: 0 20px;
  background: var(--jy-bg-card);
  border-bottom: 1px solid var(--jy-border);
  position: sticky;
  top: 0;
  z-index: 20;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}

.brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--jy-brand), #7a5cf0);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 1px;
}

.brand-title {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.2;
}

.brand-sub {
  font-size: 11px;
  color: var(--jy-text-placeholder);
  margin-top: 2px;
}

.nav {
  display: flex;
  gap: 6px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  background: transparent;
  border-radius: var(--jy-radius-sm);
  color: var(--jy-text-regular);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.nav-item:hover {
  background: var(--jy-bg-hover);
  color: var(--jy-brand);
}

.nav-item.active {
  background: var(--jy-brand-soft);
  color: var(--jy-brand);
  font-weight: 600;
}

.right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
  background: var(--jy-info);
}

.dot--success {
  background: var(--jy-success);
}

.dot--warning {
  background: var(--jy-warning);
}

.user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--jy-radius-sm);
}

.user:hover {
  background: var(--jy-bg-hover);
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--jy-brand-soft);
  color: var(--jy-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.user-name {
  font-size: 13px;
  line-height: 1.2;
}

.user-role {
  font-size: 11px;
  color: var(--jy-text-placeholder);
}

.caret {
  color: var(--jy-text-placeholder);
  font-size: 12px;
}
</style>
