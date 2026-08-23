import { Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import MainLayout from './components/MainLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Devices from './pages/Devices'
import Metrics from './pages/Metrics'
import Alerts from './pages/Alerts'
import Upload from './pages/Upload'
import Settings from './pages/Settings'
import Users from './pages/Users'
import Reports from './pages/Reports'
import Copilot from './pages/Copilot'

function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="devices" element={<Devices />} />
          <Route path="metrics" element={<Metrics />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="upload" element={<Upload />} />
          <Route path="reports" element={<Reports />} />
          <Route path="users" element={<Users />} />
          <Route path="copilot" element={<Copilot />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </ConfigProvider>
  )
}

export default App
