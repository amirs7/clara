'''
Feedback generation from repair
'''

# Python imports
import time
import traceback

# clara imports
from feedback2 import TxtFeed
from model import Var, isprimed, unprime, prime
from repair import Repair, Timeout, StructMismatch


class Feedback(object):
    '''
    Feedback result
    '''

    STATUS_REPAIRED = 10

    STATUS_STRUCT = 17
    STATUS_TIMEOUT = 18
    STATUS_ERROR = 19

    def __init__(self, impl, spec, inter, timeout=None, verbose=False,
                 ins=None, args=None, ignoreio=False, ignoreret=False,
                 entryfnc=None, allowsuboptimal=True):
        
        self.impl = impl
        self.spec = spec
        self.timeout = timeout
        self.verbose = verbose
        self.inter = inter
        self.ins = ins
        self.args = args
        self.ignoreio = ignoreio
        self.ignoreret = ignoreret
        self.entryfnc = entryfnc
        self.allowsuboptimal = allowsuboptimal
        self.start = time.time()

        self.feedback = []
        self.cost = -1
        self.size = -1
        self.large = False
        self.status = None
        self.error = None

    def generate(self):

        # Time spent waiting
        if self.timeout:
            self.timeout -= (time.time() - self.start)

        R = Repair(timeout=self.timeout, verbose=self.verbose,
                   allowsuboptimal=self.allowsuboptimal)

        try:
            self.results = R.repair(
                self.spec, self.impl, self.inter, ins=self.ins, args=self.args,
                ignoreio=self.ignoreio, ignoreret=self.ignoreret,
                entryfnc=self.entryfnc)

            self.cost = 0
            self.size = 0
            for _, repairs, _ in self.results.values():
                for (_, _, _, cost, _) in repairs:
                    self.cost += cost
                    self.size += 1
            self.large = self.islarge()
            
            self.status = self.STATUS_REPAIRED

            txtfeed = TxtFeed(self.impl, self.spec, self.results)
            txtfeed.genfeedback()
            self.feedback = list(txtfeed.feedback)

        except StructMismatch:
            self.status = self.STATUS_STRUCT
            self.error = 'no struct'
            
        except Timeout:
            self.status = self.STATUS_TIMEOUT
            self.error = 'timeout'

    def islarge(self):
        for fnc, (m, repairs, sm) in self.results.items():
            for (loc1, var1, var2, _, _) in repairs:
                loc2 = sm[loc1]

                # Added variable
                if var2 == '*':
                    return True

                # Added stmt
                if self.spec.getfnc(fnc).hasexpr(loc1, var1) \
                   and (not self.impl.getfnc(fnc).hasexpr(loc2, var2)):
                    return True

                # Swapped stmts
                expr1 = self.spec.getfnc(fnc).getexpr(loc1, var1)
                expr2 = self.impl.getfnc(fnc).getexpr(loc2, var2)
                vars1 = expr1.vars()
                vars2 = expr2.vars()

                for var1 in vars1:
                    if isprimed(var1):
                        var1 = unprime(var1)
                        var2m = m[var1]
                        var2mp = prime(var2m)
                        if var2m in vars2 and var2mp not in vars2:
                            return True
                    else:
                        var2m = m[var1]
                        var2mp = prime(var2m)
                        if var2mp in vars2 and var2m not in vars2:
                            return True

        # Nothing found
        return False

    def statusstr(self):
        if self.status == self.STATUS_REPAIRED:
            return 'repaired'
        elif self.status == self.STATUS_STRUCT:
            return 'struct'
        elif self.status == self.STATUS_TIMEOUT:
            return 'timeout'
        elif self.status == self.STATUS_ERROR:
            return 'error'
        else:
            return 'unknown<%s>' % (self.status,)

    def __repr__(self):
        return '<Feedback status=%s error=%s feedback=%s cost=%s>' % (
            self.statusstr(), self.error, self.feedback, self.cost
        )

    
def run_feedback(f):
    try:
        f.generate()
    except Exception, ex:
        f.error = traceback.format_exc()
        f.status = Feedback.STATUS_ERROR
    return f


class FeedGen(object):
    '''
    Feedback generator
    '''

    def __init__(self, verbose=False, timeout=False, pool=None,
                 allowsuboptimal=True):
        self.verbose = verbose
        self.timeout = timeout
        self.pool = pool
        if self.pool is None:
            from multiprocessing import Pool
            self.pool = Pool()
        self.allowsuboptimal = allowsuboptimal

    def generate(self, impl, specs, inter, ins=None, args=None,
                 entryfnc='main', ignoreio=False, ignoreret=False):

        self.impl = impl
        self.specs = specs

        assert len(self.specs) > 0, 'No specs!'
        
        self.inter = inter
        self.ins = ins
        self.args = args
        self.entryfnc = entryfnc
        self.ignoreio = ignoreio
        self.ignoreret = ignoreret

        tasks = [
            Feedback(
                impl, spec, inter, timeout=self.timeout, verbose=self.verbose,
                ins=self.ins, args=self.args, ignoreio=self.ignoreio,
                ignoreret=self.ignoreret, entryfnc=self.entryfnc,
                allowsuboptimal=self.allowsuboptimal)
            for spec in specs]
        results = self.pool.map(run_feedback, tasks)

        feedback = None
        feedbacks = []
        for res in results:
            # Immediately return error or timeout
            if res.status == Feedback.STATUS_ERROR:
                return res

            # Return of remember timeout results
            # (depending if suboptimal feedback is allowed or not)
            if res.status == Feedback.STATUS_TIMEOUT:
                if self.allowsuboptimal:
                    feedback = res
                else:
                    return res
            
            # Remember struct problem
            elif res.status == Feedback.STATUS_STRUCT:
                feedback = res

            # Remember repaired with cost
            elif res.status == Feedback.STATUS_REPAIRED:
                feedbacks.append((res.cost, res))

            else:
                print 'unknown status: %s' % (res.statusstr(),)
                assert False

        # Return best repaired if there are any
        if len(feedbacks) > 0:
            feedbacks.sort()
            return feedbacks[0][1]

        # Otherwise return something
        return feedback