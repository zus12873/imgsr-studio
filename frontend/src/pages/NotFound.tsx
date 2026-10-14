import { Link } from "react-router";

export default function NotFound() {
  return (
    <div className="p-8 text-center">
      <p className="text-lg">页面不存在</p>
      <Link to="/" className="text-indigo-600">
        回到工作台
      </Link>
    </div>
  );
}
