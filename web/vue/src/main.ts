import { createApp } from 'vue'
import App from './App.vue'
import { createCandidateRouter } from './router'
import '../../src/styles/global.css'

const router = createCandidateRouter()
const app = createApp(App).use(router)
// Resolve the initial deep link before App decides the anonymous home route.
void router.isReady().then(() => app.mount('#root'))
