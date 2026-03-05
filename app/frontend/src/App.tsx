import { FlightProvider } from './context/FlightContext';
import Header from './components/Header/Header';
import FlightList from './components/FlightList/FlightList';
import AirportMap from './components/Map/AirportMap';
import FlightDetail from './components/FlightDetail/FlightDetail';
import GateStatus from './components/GateStatus/GateStatus';

function AppContent() {
  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden">
      <Header />
      <main className="flex-1 flex overflow-hidden">
        {/* Left panel: Flight List */}
        <div className="w-80 flex-shrink-0 overflow-hidden">
          <FlightList />
        </div>

        {/* Center: Airport Map */}
        <div className="flex-1 overflow-hidden">
          <AirportMap />
        </div>

        {/* Right panel: Flight Detail + Gate Status */}
        <div className="w-80 flex-shrink-0 overflow-y-auto bg-slate-50 p-4 space-y-4">
          <FlightDetail />
          <GateStatus />
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <FlightProvider>
      <AppContent />
    </FlightProvider>
  );
}

export default App;
