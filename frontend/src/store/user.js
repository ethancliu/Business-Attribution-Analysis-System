/** 登录用户与公开配置。 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import * as authApi from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const me = ref(null)
  const publicConfig = ref(null)
  const loading = ref(false)
  const loaded = ref(false)

  const isLoggedIn = computed(() => !!me.value)
  const isAdmin = computed(() => me.value?.role === 'admin')
  const roleLabelText = computed(() => (me.value?.role === 'admin' ? '系统管理员' : '分析人员'))
  const displayName = computed(() => me.value?.display_name || me.value?.username || '未登录')

  /** 拉取当前用户；未登录（401）时静默返回 null，由路由守卫跳登录页。 */
  async function fetchMe({ silent = false } = {}) {
    if (!silent) loading.value = true
    try {
      me.value = await authApi.fetchMe()
      return me.value
    } catch (err) {
      if (err?.status === 401 || err?.status === 403) {
        me.value = null
        return null
      }
      throw err
    } finally {
      loading.value = false
      loaded.value = true
    }
  }

  async function fetchPublicConfig() {
    if (publicConfig.value) return publicConfig.value
    try {
      publicConfig.value = await authApi.fetchPublicConfig()
    } catch {
      // 公开配置拉不到不影响主流程，前端各自退到默认值
      publicConfig.value = null
    }
    return publicConfig.value
  }

  function login() {
    authApi.redirectToLogin()
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // 后端登出失败也要清掉本地状态，否则界面会一直停留在已登录
    }
    me.value = null
  }

  return {
    me,
    publicConfig,
    loading,
    loaded,
    isLoggedIn,
    isAdmin,
    roleLabelText,
    displayName,
    fetchMe,
    fetchPublicConfig,
    login,
    logout,
  }
})
