/** 管理控制台接口（docs/API.md §11）：全部需要 admin 角色，否则 403。 */

import { http } from './http'

export function getOverview() {
  return http.get('/api/admin/overview')
}

export function listConfigs(group) {
  return http.get('/api/admin/configs', { group })
}

/** 修改配置项：后端会自动热重载，无需重启。 */
export function updateConfig(configKey, configValue) {
  return http.post('/api/admin/configs/update', {
    config_key: configKey,
    config_value: String(configValue),
  })
}

/** 全量或按分组热重载配置。groups 留空表示全量。 */
export function reloadConfig(groups = []) {
  return http.post('/api/admin/reload', { groups })
}

export function listLogs({ taskId, logType, limit } = {}) {
  return http.get('/api/admin/logs', { task_id: taskId, log_type: logType, limit })
}

export function listDatasources() {
  return http.get('/api/admin/datasources')
}

export function toggleDatasource(id) {
  return http.post('/api/admin/datasources/toggle', { id })
}

export function listFeatureToggles() {
  return http.get('/api/admin/feature-toggles')
}

export function toggleFeature(configKey, enabled) {
  return http.post('/api/admin/feature-toggles/toggle', { config_key: configKey, enabled })
}

export function getAuthCenter() {
  return http.get('/api/admin/auth-center')
}

export function listScenarios() {
  return http.get('/api/admin/scenarios')
}

export function listTools() {
  return http.get('/api/admin/tools')
}
