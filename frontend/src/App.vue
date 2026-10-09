<script setup>
/**
 * 应用外壳：登录页不套布局，其余页面统一「顶栏 + 内容区」。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'

const route = useRoute()
const isBlank = computed(() => route.meta.blank === true)
</script>

<template>
  <div class="app-shell">
    <AppHeader v-if="!isBlank" />
    <main class="app-main" :class="{ 'app-main--blank': isBlank }">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.app-main--blank {
  height: 100vh;
}
</style>
