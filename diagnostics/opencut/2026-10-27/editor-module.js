import { createHotContext as __vite__createHotContext } from "/@vite/client";import.meta.hot = __vite__createHotContext("/src/routes/editor.tsx");const $$splitComponentImporter = () => import("/src/routes/editor.tsx?tsr-split=component");
import { lazyRouteComponent } from "/node_modules/@tanstack/react-router/dist/esm/index.dev.js?v=347ad6e1";
import { createFileRoute } from "/node_modules/@tanstack/react-router/dist/esm/index.dev.js?v=347ad6e1";
const TSRSplitComponent = (() => {
	const hot = import.meta.hot;
	const hotData = hot ? hot.data ??= {} : undefined;
	return hotData?.["tsr-split-component:component"] ?? lazyRouteComponent($$splitComponentImporter, "component");
})();
if (import.meta.hot) {
	(import.meta.hot.data ??= {})["tsr-split-component:component"] = TSRSplitComponent;
}
export const Route = createFileRoute("/editor")({ component: TSRSplitComponent });
const hot = import.meta.hot;
if (hot && typeof window !== "undefined") {
	hot.data ??= {};
	const tsrReactRefresh = window.__TSR_REACT_REFRESH__ ??= (() => {
		const ignoredExportsById = new Map();
		const previousGetIgnoredExports = window.__getReactRefreshIgnoredExports;
		window.__getReactRefreshIgnoredExports = (ctx) => {
			const ignoredExports = previousGetIgnoredExports?.(ctx) ?? [];
			const moduleIgnored = ignoredExportsById.get(ctx.id) ?? [];
			return [...ignoredExports, ...moduleIgnored];
		};
		return { ignoredExportsById };
	})();
	tsrReactRefresh.ignoredExportsById.set("/tmp/videogen-opencut-eval-20261027/apps/web/src/routes/editor.tsx", ["Route"]);
}
export function TSRFastRefreshAnchor() {
	return null;
}
_c = TSRFastRefreshAnchor;
if (import.meta.hot) {
	const hot = import.meta.hot;
	const hotData = hot.data ??= {};
	const handleRouteUpdate = function handleRouteUpdate(routeId, newRoute) {
		const router = window.__TSR_ROUTER__;
		const oldRoute = router.routesById[routeId];
		if (!oldRoute) return;
		const generatedRouteOptionKeys = new Set([
			"id",
			"path",
			"getParentRoute"
		]);
		const generatedRouteOptions = {};
		generatedRouteOptionKeys.forEach((key) => {
			if (key in oldRoute.options) generatedRouteOptions[key] = oldRoute.options[key];
		});
		const preserveComponentIdentity = "shellComponent" in oldRoute.options === "shellComponent" in newRoute.options;
		const componentKeys = [
			"component",
			"shellComponent",
			"pendingComponent",
			"errorComponent",
			"notFoundComponent"
		];
		if (preserveComponentIdentity) componentKeys.forEach((key) => {
			if (key in oldRoute.options && key in newRoute.options) newRoute.options[key] = oldRoute.options[key];
		});
		const nextOptions = {
			...newRoute.options,
			...generatedRouteOptions
		};
		oldRoute.options = nextOptions;
		oldRoute.update(nextOptions);
		router._replaceRouteChunk(oldRoute, newRoute.lazyFn);
		router.setRoutes(router.buildRouteTree());
		syncHotRouteExport(oldRoute);
		router.resolvePathCache.clear();
		router._refreshRoute?.();
		function syncHotRouteExport(liveRoute) {
			newRoute.options = liveRoute.options;
			newRoute.parentRoute = liveRoute.parentRoute;
			newRoute._path = liveRoute._path;
			newRoute._id = liveRoute._id;
			newRoute._fullPath = liveRoute._fullPath;
			newRoute._to = liveRoute._to;
		}
	};
	const initialRouteId = "/editor" ?? hotData["tsr-route-id"];
	if (initialRouteId) {
		hotData["tsr-route-id"] = initialRouteId;
	}
	const existingRoute = typeof window !== "undefined" && initialRouteId ? window.__TSR_ROUTER__?.routesById?.[initialRouteId] : undefined;
	if (initialRouteId && existingRoute && existingRoute !== Route) {
		handleRouteUpdate(initialRouteId, Route);
		hotData["tsr-route-update-handled"] = Route;
	}
	hot.accept((newModule) => {
		if (Route && newModule && newModule.Route) {
			const routeId = hotData["tsr-route-id"] ?? "/editor";
			if (routeId) {
				hotData["tsr-route-id"] = routeId;
			}
			if (hotData["tsr-route-update-handled"] === newModule.Route) {
				delete hotData["tsr-route-update-handled"];
				return;
			}
			handleRouteUpdate(routeId, newModule.Route);
		}
	});
}
var _c;
$RefreshReg$(_c, "TSRFastRefreshAnchor");
import * as RefreshRuntime from "/@react-refresh";
const inWebWorker = typeof WorkerGlobalScope !== 'undefined' && self instanceof WorkerGlobalScope;
import * as __vite_react_currentExports from "/src/routes/editor.tsx";
if (import.meta.hot && !inWebWorker) {
  if (!window.$RefreshReg$) {
    throw new Error(
      "@vitejs/plugin-react can't detect preamble. Something is wrong."
    );
  }

  const currentExports = __vite_react_currentExports;
  queueMicrotask(() => {
    RefreshRuntime.registerExportsForReactRefresh("/tmp/videogen-opencut-eval-20261027/apps/web/src/routes/editor.tsx", currentExports);
    import.meta.hot.accept((nextExports) => {
      if (!nextExports) return;
      const invalidateMessage = RefreshRuntime.validateRefreshBoundaryAndEnqueueUpdate("/tmp/videogen-opencut-eval-20261027/apps/web/src/routes/editor.tsx", currentExports, nextExports);
      if (invalidateMessage) import.meta.hot.invalidate(invalidateMessage);
    });
  });
}
function $RefreshReg$(type, id) { return RefreshRuntime.register(type, "/tmp/videogen-opencut-eval-20261027/apps/web/src/routes/editor.tsx" + ' ' + id); }
function $RefreshSig$() { return RefreshRuntime.createSignatureFunctionForTransform(); }

//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJtYXBwaW5ncyI6Ijs7QUFBQSxTQUFBQSx1QkFBQTtBQUFBLE1BQUFDLDJCQUFBO0NBQUEsTUFBQUMsTUFBQUMsWUFBQUQ7Q0FBQSxNQUFBRSxVQUFBRixVQUFBRyxTQUFBLEtBQUFDO0NBQUEsT0FBQUYsVUFBQSxvQ0FBQUcsbUJBQUFDLDBCQUFBO0FBQUE7QUFBQSxJQUFBTCxZQUFBRCxLQUFBO0NBQUEsQ0FBQUMsWUFBQUQsSUFBQUcsU0FBQSx1Q0FBQUo7QUFBQTtBQUVBLGFBQUFRLFFBQUFULGdCQUFBLGFBQUFVLFdBQUFULGtCQUFBO0FBQUEsTUFBQUMsTUFBQUMsWUFBQUQ7QUFBQSxJQUFBQSxPQUFBLE9BQUFTLFdBQUE7Q0FBQVQsSUFBQUcsU0FBQTtDQUFBLE1BQUFPLGtCQUFBRCxPQUFBRSxpQ0FBQTtFQUFBLE1BQUFDLHFCQUFBLElBQUFDLElBQUE7RUFBQSxNQUFBQyw0QkFBQUwsT0FBQU07RUFBQU4sT0FBQU0sbUNBQUFDLFFBQUE7R0FBQSxNQUFBQyxpQkFBQUgsNEJBQUFFLEdBQUE7R0FBQSxNQUFBRSxnQkFBQU4sbUJBQUFPLElBQUFILElBQUFJLEVBQUE7R0FBQSxXQUFBSCxnQkFBQSxHQUFBQyxhQUFBO0VBQUE7RUFBQSxTQUFBTixtQkFBQTtDQUFBO0NBQUFGLGdCQUFBRSxtQkFBQVMsSUFBQTtBQUFBO0FBQUEsZ0JBQUFDLHVCQUFBO0NBQUE7QUFBQTs7QUFBQSxJQUFBckIsWUFBQUQsS0FBQTtDQUFBLE1BQUFBLE1BQUFDLFlBQUFEO0NBQUEsTUFBQUUsVUFBQUYsSUFBQUcsU0FBQTtDQUFBLE1BQUFvQixvQkFBQSxTQUFBQSxrQkFBQUMsU0FBQUMsVUFBQTtFQUFBLE1BQUFDLFNBQUFqQixPQUFBa0I7RUFBQSxNQUFBQyxXQUFBRixPQUFBRyxXQUFBTDtFQUFBLEtBQUFJLFVBQUE7RUFBQSxNQUFBRSwyQkFBQSxJQUFBQyxJQUFBO0dBQUE7R0FBQTtHQUFBO0VBQUE7RUFBQSxNQUFBQyx3QkFBQTtFQUFBRix5QkFBQUcsU0FBQUMsUUFBQTtHQUFBLElBQUFBLE9BQUFOLFNBQUFPLFNBQUFILHNCQUFBRSxPQUFBTixTQUFBTyxRQUFBRDtFQUFBO0VBQUEsTUFBQUUsNEJBQUEsb0JBQUFSLFNBQUFPLFlBQUEsb0JBQUFWLFNBQUFVO0VBQUEsTUFBQUUsZ0JBQUE7R0FBQTtHQUFBO0dBQUE7R0FBQTtHQUFBO0VBQUE7RUFBQSxJQUFBRCwyQkFBQUMsY0FBQUosU0FBQUMsUUFBQTtHQUFBLElBQUFBLE9BQUFOLFNBQUFPLFdBQUFELE9BQUFULFNBQUFVLFNBQUFWLFNBQUFVLFFBQUFELE9BQUFOLFNBQUFPLFFBQUFEO0VBQUE7RUFBQSxNQUFBSSxjQUFBO0dBQUEsR0FBQWIsU0FBQVU7R0FBQSxHQUFBSDtFQUFBO0VBQUFKLFNBQUFPLFVBQUFHO0VBQUFWLFNBQUFXLE9BQUFELFdBQUE7RUFBQVosT0FBQWMsbUJBQUFaLFVBQUFILFNBQUFnQixNQUFBO0VBQUFmLE9BQUFnQixVQUFBaEIsT0FBQWlCLGVBQUE7RUFBQUMsbUJBQUFoQixRQUFBO0VBQUFGLE9BQUFtQixpQkFBQUMsTUFBQTtFQUFBcEIsT0FBQXFCLGdCQUFBO0VBQUEsU0FBQUgsbUJBQUFJLFdBQUE7R0FBQXZCLFNBQUFVLFVBQUFhLFVBQUFiO0dBQUFWLFNBQUF3QixjQUFBRCxVQUFBQztHQUFBeEIsU0FBQXlCLFFBQUFGLFVBQUFFO0dBQUF6QixTQUFBMEIsTUFBQUgsVUFBQUc7R0FBQTFCLFNBQUEyQixZQUFBSixVQUFBSTtHQUFBM0IsU0FBQTRCLE1BQUFMLFVBQUFLO0VBQUE7Q0FBQTtDQUFBLE1BQUFDLGlCQUFBLGFBQUFwRCxRQUFBO0NBQUEsSUFBQW9ELGdCQUFBO0VBQUFwRCxRQUFBLGtCQUFBb0Q7Q0FBQTtDQUFBLE1BQUFDLGdCQUFBLE9BQUE5QyxXQUFBLGVBQUE2QyxpQkFBQTdDLE9BQUFrQixnQkFBQUUsYUFBQXlCLGtCQUFBbEQ7Q0FBQSxJQUFBa0Qsa0JBQUFDLG1DQUFBaEQsT0FBQTtFQUFBZ0Isa0JBQUErQixnQkFBQS9DLEtBQUE7RUFBQUwsUUFBQSw4QkFBQUs7Q0FBQTtDQUFBUCxJQUFBd0QsUUFBQUMsY0FBQTtFQUFBLElBQUFsRCxTQUFBa0QsdUJBQUFsRCxPQUFBO0dBQUEsTUFBQWlCLFVBQUF0QixRQUFBO0dBQUEsSUFBQXNCLFNBQUE7SUFBQXRCLFFBQUEsa0JBQUFzQjtHQUFBO0dBQUEsSUFBQXRCLFFBQUEsZ0NBQUF1RCxVQUFBbEQsT0FBQTtJQUFBLE9BQUFMLFFBQUE7SUFBQTtHQUFBO0dBQUFxQixrQkFBQUMsU0FBQWlDLFVBQUFsRCxLQUFBO0VBQUE7Q0FBQTtBQUFBIiwibmFtZXMiOlsiY3JlYXRlRmlsZVJvdXRlIiwiVFNSU3BsaXRDb21wb25lbnQiLCJob3QiLCJpbXBvcnQiLCJob3REYXRhIiwiZGF0YSIsInVuZGVmaW5lZCIsImxhenlSb3V0ZUNvbXBvbmVudCIsIiQkc3BsaXRDb21wb25lbnRJbXBvcnRlciIsIlJvdXRlIiwiY29tcG9uZW50Iiwid2luZG93IiwidHNyUmVhY3RSZWZyZXNoIiwiX19UU1JfUkVBQ1RfUkVGUkVTSF9fIiwiaWdub3JlZEV4cG9ydHNCeUlkIiwiTWFwIiwicHJldmlvdXNHZXRJZ25vcmVkRXhwb3J0cyIsIl9fZ2V0UmVhY3RSZWZyZXNoSWdub3JlZEV4cG9ydHMiLCJjdHgiLCJpZ25vcmVkRXhwb3J0cyIsIm1vZHVsZUlnbm9yZWQiLCJnZXQiLCJpZCIsInNldCIsIlRTUkZhc3RSZWZyZXNoQW5jaG9yIiwiaGFuZGxlUm91dGVVcGRhdGUiLCJyb3V0ZUlkIiwibmV3Um91dGUiLCJyb3V0ZXIiLCJfX1RTUl9ST1VURVJfXyIsIm9sZFJvdXRlIiwicm91dGVzQnlJZCIsImdlbmVyYXRlZFJvdXRlT3B0aW9uS2V5cyIsIlNldCIsImdlbmVyYXRlZFJvdXRlT3B0aW9ucyIsImZvckVhY2giLCJrZXkiLCJvcHRpb25zIiwicHJlc2VydmVDb21wb25lbnRJZGVudGl0eSIsImNvbXBvbmVudEtleXMiLCJuZXh0T3B0aW9ucyIsInVwZGF0ZSIsIl9yZXBsYWNlUm91dGVDaHVuayIsImxhenlGbiIsInNldFJvdXRlcyIsImJ1aWxkUm91dGVUcmVlIiwic3luY0hvdFJvdXRlRXhwb3J0IiwicmVzb2x2ZVBhdGhDYWNoZSIsImNsZWFyIiwiX3JlZnJlc2hSb3V0ZSIsImxpdmVSb3V0ZSIsInBhcmVudFJvdXRlIiwiX3BhdGgiLCJfaWQiLCJfZnVsbFBhdGgiLCJfdG8iLCJpbml0aWFsUm91dGVJZCIsImV4aXN0aW5nUm91dGUiLCJhY2NlcHQiLCJuZXdNb2R1bGUiXSwiaWdub3JlTGlzdCI6W10sInNvdXJjZXMiOlsiZWRpdG9yLnRzeCJdLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgeyBjcmVhdGVGaWxlUm91dGUgfSBmcm9tICdAdGFuc3RhY2svcmVhY3Qtcm91dGVyJ1xuXG5leHBvcnQgY29uc3QgUm91dGUgPSBjcmVhdGVGaWxlUm91dGUoJy9lZGl0b3InKSh7IGNvbXBvbmVudDogRWRpdG9yIH0pXG5cbmZ1bmN0aW9uIEVkaXRvcigpIHtcbiAgcmV0dXJuIChcbiAgICA8bWFpbj5cbiAgICAgIDxoMT5FZGl0b3I8L2gxPlxuICAgICAgPHA+Q29taW5nIHNvb24uPC9wPlxuICAgIDwvbWFpbj5cbiAgKVxufVxuIl0sImZpbGUiOiIvdG1wL3ZpZGVvZ2VuLW9wZW5jdXQtZXZhbC0yMDI2MTAyNy9hcHBzL3dlYi9zcmMvcm91dGVzL2VkaXRvci50c3gifQ==