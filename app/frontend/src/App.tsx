import AirportMap from './components/Map/AirportMap'

function App() {
  return (
    <div className="h-screen w-screen flex flex-col">
      <header className="bg-slate-800 text-white px-4 py-3 flex items-center justify-between shadow-lg z-10">
        <h1 className="text-xl font-bold">Airport Digital Twin</h1>
        <div className="flex items-center gap-4 text-sm">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-gray-500"></span>
            Ground
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-green-500"></span>
            Climbing
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-orange-500"></span>
            Descending
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-blue-500"></span>
            Cruising
          </span>
        </div>
      </header>
      <main className="flex-1">
        <AirportMap />
      </main>
    </div>
  )
}

export default App
