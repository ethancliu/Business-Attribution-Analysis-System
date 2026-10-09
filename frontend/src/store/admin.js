/** 管理控制台状态：配置、功能开关、数据源、场景与工具清单、运行日志。 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import * as adminApi from '@/api/admin'

export const useAdminStore = defineStore('admin', () => {
  const overview = ref(null)
  const configs = ref([])
  const configGroups = ref([])
  const activeGroup = ref('')
  const featureToggles = ref([])
  const datasources = ref([])
  const authCenter = ref(null)
  const scenarios = ref([])
  const tools = ref([])
  const logs = ref([])
  const loading = ref(false)
  const lastReload = ref(null)

  const filteredConfigs = computed(() =>
    activeGroup.value ? configs.value.filter((c) => c.config_group === activeGroup.value) : configs.value,
  )

  async function loadAll() {
    loading.value = true
    try {
      const [ov, cfg, feat, ds, ac, sc, tl] = await Promise.all([
        adminApi.getOverview().catch(() => null),
        adminApi.listConfigs().catch(() => ({ items: [], groups: [], total: 0 })),
        adminApi.listFeatureToggles().catch(() => ({ items: [] })),
        adminApi.listDatasources().catch(() => ({ items: [] })),
        adminApi.getAuthCenter().catch(() => null),
        adminApi.listScenarios().catch(() => ({ items: [] })),
        adminApi.listTools().catch(() => ({ items: [] })),
      ])
      overview.value = ov
      configs.value = cfg.items || []
      configGroups.value = cfg.groups || []
      featureToggles.value = feat.items || []
      datasources.value = ds.items || []
      authCenter.value = ac
      scenarios.value = sc.items || []
      tools.value = tl.items || []
    } finally {
      loading.value = false
    }
  }

  async function reload(groups = []) {
    const res = await adminApi.reloadConfig(groups)
    lastReload.value = res
    await Promise.all([refreshConfigs(), refreshToggles()])
    return res
  }

  async function refreshConfigs() {
    const cfg = await adminApi.listConfigs()
    configs.value = cfg.items || []
    configGroups.value = cfg.groups || []
  }

  async function refreshToggles() {
    const feat = await adminApi.listFeatureToggles()
    featureToggles.value = feat.items || []
  }

  async function saveConfig(configKey, configValue) {
    const res = await adminApi.updateConfig(configKey, configValue)
    await refreshConfigs()
    return res
  }

  async function toggleFeature(configKey, enabled) {
    const res = await adminApi.toggleFeature(configKey, enabled)
    const target = featureToggles.value.find((t) => t.config_key === configKey)
    if (target) target.enabled = res.enabled ?? enabled
    await refreshConfigs()
    return res
  }

  async function toggleDatasource(id) {
    const res = await adminApi.toggleDatasource(id)
    const target = datasources.value.find((d) => d.id === id)
    if (target) target.status = res.status
    return res
  }

  async function loadLogs(params) {
    const res = await adminApi.listLogs(params)
    logs.value = res.items || []
    return res
  }

  async function refreshOverview() {
    overview.value = await adminApi.getOverview()
    return overview.value
  }

  return {
    overview,
    configs,
    configGroups,
    activeGroup,
    featureToggles,
    datasources,
    authCenter,
    scenarios,
    tools,
    logs,
    loading,
    lastReload,
    filteredConfigs,
    loadAll,
    reload,
    refreshConfigs,
    refreshToggles,
    saveConfig,
    toggleFeature,
    toggleDatasource,
    loadLogs,
    refreshOverview,
  }
})
