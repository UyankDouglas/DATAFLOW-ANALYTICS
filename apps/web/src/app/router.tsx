import { createBrowserRouter, type RouteObject } from 'react-router'

import { AppLayout } from '@/layouts/app-layout'
import { AuthLayout } from '@/layouts/auth-layout'
import { LoginPage } from '@/pages/auth/login-page'
import { ComingSoonPage } from '@/pages/coming-soon-page'
import { NotFoundPage } from '@/pages/not-found-page'
import { COMING_SOON } from '@/routes/nav'

/** Carrega a página sob demanda (code splitting por rota). */
function page<M>(
  loader: () => Promise<M>,
  pick: (module: M) => React.ComponentType,
): RouteObject['lazy'] {
  return async () => ({ Component: pick(await loader()) })
}

export const router = createBrowserRouter([
  {
    element: <AuthLayout />,
    children: [
      { path: '/entrar', element: <LoginPage /> },
      {
        path: '/cadastro',
        lazy: page(
          () => import('@/pages/auth/register-page'),
          (m) => m.RegisterPage,
        ),
      },
      {
        path: '/recuperar-senha',
        lazy: page(
          () => import('@/pages/auth/password-pages'),
          (m) => m.ForgotPasswordPage,
        ),
      },
    ],
  },
  {
    element: <AuthLayout guestOnly={false} />,
    children: [
      {
        path: '/redefinir-senha',
        lazy: page(
          () => import('@/pages/auth/password-pages'),
          (m) => m.ResetPasswordPage,
        ),
      },
    ],
  },
  {
    element: <AppLayout />,
    children: [
      {
        index: true,
        lazy: page(
          () => import('@/pages/overview/overview-page'),
          (m) => m.OverviewPage,
        ),
      },
      {
        path: '/datasets',
        lazy: page(
          () => import('@/pages/datasets/datasets-page'),
          (m) => m.DatasetsPage,
        ),
      },
      {
        path: '/datasets/:datasetId',
        lazy: page(
          () => import('@/pages/datasets/dataset-detail-page'),
          (m) => m.DatasetDetailPage,
        ),
      },
      {
        path: '/datasets/:datasetId/preview',
        lazy: page(
          () => import('@/pages/datasets/preview-page'),
          (m) => m.PreviewPage,
        ),
      },
      {
        path: '/datasets/:datasetId/explorar',
        lazy: page(
          () => import('@/pages/datasets/explorer-page'),
          (m) => m.ExplorerPage,
        ),
      },
      {
        path: '/importar',
        lazy: page(
          () => import('@/pages/import/import-page'),
          (m) => m.ImportPage,
        ),
      },
      {
        path: '/processamentos',
        lazy: page(
          () => import('@/pages/jobs/jobs-page'),
          (m) => m.JobsPage,
        ),
      },
      {
        path: '/processamentos/:jobId',
        lazy: page(
          () => import('@/pages/jobs/job-detail-page'),
          (m) => m.JobDetailPage,
        ),
      },
      {
        path: '/explorer',
        lazy: page(
          () => import('@/pages/datasets/explorer-page'),
          (m) => m.ExplorerIndexPage,
        ),
      },
      {
        path: '/usuarios',
        lazy: page(
          () => import('@/pages/users-page'),
          (m) => m.UsersPage,
        ),
      },
      ...Object.entries(COMING_SOON).map(([path, info]) => ({
        path,
        element: <ComingSoonPage {...info} />,
      })),
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
