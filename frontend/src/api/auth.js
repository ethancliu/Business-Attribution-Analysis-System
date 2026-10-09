/** 认证相关接口：登录是整页跳转（后端 302 到认证中心），前端只负责发起与查询身份。 */

import { http } from './http'

/**
 * 发起登录：直接跳转到后端 /auth/login。
 *
 * 后端会 302 到认证中心的授权页，授权码回调后由后端换取令牌并种下
 * HttpOnly Cookie，最后 302 回前端首页。前端全程无需接触令牌。
 */
export function redirectToLogin() {
  window.location.href = '/auth/login'
}

/** 当前登录用户；未登录时后端返回 401。 */
export function fetchMe() {
  return http.get('/api/auth/me')
}

export function logout() {
  return http.post('/api/auth/logout')
}

/** 前端可读的公开配置（系统名 / 上传限制 / 分析窗口）。 */
export function fetchPublicConfig() {
  return http.get('/api/config/public')
}

export function fetchHealth() {
  return http.get('/healthz')
}
